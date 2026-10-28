import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from updater import (publish, read_update, stage_update, replace_install,
                     InstallLock, unpack_checked, version_tuple)
from pdf_export import atomic_copy
from app import Application
from types import SimpleNamespace


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.install = self.root / 'ContractPrintApp'
        self.install.mkdir()
        (self.install / 'ContractPrintApp.exe').write_bytes(b'old exe')
        (self.install / '_internal').mkdir()
        self.build = self.root / 'build'
        self.build.mkdir()
        (self.build / 'ContractPrintApp.exe').write_bytes(b'new exe')
        (self.build / '_internal').mkdir()
        (self.build / '_internal' / 'python.dll').write_bytes(b'runtime')
        (self.build / 'BUILD_INFO.txt').write_text('ContractPrintApp 1.11.0\n',encoding='utf-8')
        self.share = self.root / 'share'

    def prepare(self):
        publish(self.build, self.share, '1.11.0')
        return stage_update(read_update(self.share, '1.9.1'), self.install)

    def test_publish_stage_install_and_keep_settings_and_backup(self):
        (self.build / 'settings.json').write_text('must not publish')
        (self.install / 'settings.json').write_text('local settings')
        data = self.install / 'userdata';data.mkdir();(data / 'firms.json').write_text('private')
        stage = self.prepare()
        def validate(folder):
            self.assertEqual((folder / 'ContractPrintApp.exe').read_bytes(), b'new exe')
            self.assertEqual((folder / 'settings.json').read_text(), 'local settings')
            self.assertEqual((folder / 'userdata' / 'firms.json').read_text(), 'private')
        backup = replace_install(self.install, stage, validate)
        self.assertEqual((backup / 'ContractPrintApp.exe').read_bytes(), b'old exe')
        # Subsequent updates must not be blocked by the previous backup.
        (self.build / 'BUILD_INFO.txt').write_text('ContractPrintApp 1.11.1\n',encoding='utf-8')
        publish(self.build, self.share, '1.11.1')
        second = stage_update(read_update(self.share, '1.11.0'), self.install)
        replace_install(self.install, second, validate)
        self.assertIsNone(read_update(self.share, '1.11.1'))

    def test_failed_new_version_rolls_back(self):
        stage = self.prepare()
        def fail(folder):raise RuntimeError('GUI failed')
        with self.assertRaisesRegex(RuntimeError, 'GUI failed'):
            replace_install(self.install, stage, fail)
        self.assertEqual((self.install / 'ContractPrintApp.exe').read_bytes(), b'old exe')

    def test_corrupt_archive_leaves_installation_untouched(self):
        archive = publish(self.build, self.share, '1.11.0')
        with archive.open('ab') as f:f.write(b'corruption')
        with self.assertRaisesRegex(ValueError, 'сумма'):
            stage_update(read_update(self.share, '1.9.1'), self.install)
        self.assertEqual((self.install / 'ContractPrintApp.exe').read_bytes(), b'old exe')
        self.assertFalse(list(self.root.glob('.ContractPrintApp-stage-*')))

    def test_malicious_archive_paths_and_source_archive_rejected(self):
        for name in ('../escape', '/absolute', 'a\\escape', 'C:/escape', 'file. '):
            with self.subTest(name=name):
                archive = self.root / 'bad.zip'
                with zipfile.ZipFile(archive, 'w') as z:z.writestr(name, b'bad')
                with self.assertRaises(ValueError):unpack_checked(archive, self.root / 'stage')
        with zipfile.ZipFile(archive, 'w') as z:z.writestr('app.py', 'source code')
        with self.assertRaisesRegex(ValueError, 'готовой Windows'):
            unpack_checked(archive, self.root / 'stage')

    def test_reject_path_in_manifest(self):
        publish(self.build, self.share, '1.11.0')
        manifest = self.share / 'update-ContractPrintApp.json'
        data = json.loads(manifest.read_text());data['archive'] = '../private.zip'
        manifest.write_text(json.dumps(data))
        with self.assertRaises(ValueError):read_update(self.share, '1.9.1')
        self.assertGreater(version_tuple('1.11.0'), version_tuple('1.9.99'))

    def test_running_instances_block_update_and_update_blocks_start(self):
        one = InstallLock(self.install).acquire()
        self.addCleanup(one.close)
        two = InstallLock(self.install).acquire()
        self.addCleanup(two.close)
        try:
            with self.assertRaises(OSError):InstallLock(self.install, exclusive=True).acquire()
        finally:one.close();two.close()
        writer = InstallLock(self.install, exclusive=True).acquire()
        try:
            with self.assertRaises(OSError):InstallLock(self.install).acquire()
        finally:writer.close()


class SaveTests(unittest.TestCase):
    def test_repeat_save_replace_copy_and_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp);source = folder / 'generated.pdf';dest = folder / 'card.pdf'
            source.write_bytes(b'new');dest.write_bytes(b'old')
            app = SimpleNamespace(need=lambda:True, refresh=lambda:None, target=lambda:dest,
                outputs={'duplex':source}, mark_saved=lambda:None, remember=lambda:None,
                status=SimpleNamespace(set=lambda text:None), saved_dialog=lambda path:None)
            with patch('app.messagebox.askyesnocancel', return_value=True), patch('app.messagebox.showerror') as errors:
                Application.save(app)
                self.assertEqual(dest.read_bytes(), b'new');errors.assert_not_called()
            source.write_bytes(b'second')
            with patch('app.messagebox.askyesnocancel', return_value=False):Application.save(app)
            self.assertEqual(dest.read_bytes(), b'new')
            self.assertEqual((folder / 'card (2).pdf').read_bytes(), b'second')
            with patch('app.messagebox.askyesnocancel', return_value=None):Application.save(app)
            self.assertEqual(dest.read_bytes(), b'new')
            self.assertFalse((folder / 'card (3).pdf').exists())

    def test_locked_destination_is_not_deleted_and_temp_is_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.pdf';dest=Path(tmp)/'card.pdf'
            source.write_bytes(b'new');dest.write_bytes(b'old')
            with patch('pdf_export.os.replace', side_effect=PermissionError('locked')):
                with self.assertRaisesRegex(PermissionError, 'Закройте этот файл'):
                    atomic_copy(source, dest)
            self.assertEqual(dest.read_bytes(), b'old')
            self.assertFalse(list(Path(tmp).glob('.contractprintapp-*')))

    def test_no_success_if_destination_did_not_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source.pdf';dest=Path(tmp)/'card.pdf'
            source.write_bytes(b'new');dest.write_bytes(b'old')
            with patch('pdf_export.os.replace'):
                with self.assertRaisesRegex(OSError, 'содержимое файла отличается'):
                    atomic_copy(source,dest)
