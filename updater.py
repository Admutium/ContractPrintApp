"""Private share updates. The share must grant write access only to publishers.

SHA-256 detects corruption; the Windows share ACL is the trust boundary.
No GitHub credentials or organisation data are transmitted.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile

MAX_ARCHIVE = 1024 * 1024 * 1024


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+\.\d+', value):
        raise ValueError('Некорректный номер версии обновления.')
    return tuple(map(int, value.split('.')))


def read_update(folder, current):
    folder = Path(folder)
    path = folder / 'update-ContractPrintApp.json'
    with path.open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('Слишком большой файл update-ContractPrintApp.json.')
    data = json.loads(raw)
    if data.get('product') != 'ContractPrintApp':
        raise ValueError('Этот пакет предназначен для другого приложения.')
    if version_tuple(data['version']) <= version_tuple(current):
        return None
    archive = data.get('archive', '')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.zip', archive):
        raise ValueError('В update-ContractPrintApp.json требуется имя ZIP без пути.')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', data.get('sha256', '')):
        raise ValueError('В update-ContractPrintApp.json отсутствует SHA-256 архива.')
    return {**data, 'path': str(folder / archive)}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def check_bundle_version(folder, version):
    try:
        line=(Path(folder)/'BUILD_INFO.txt').read_text(encoding='utf-8').splitlines()[0]
    except (OSError,IndexError) as e:
        raise ValueError('В сборке отсутствует BUILD_INFO.txt с номером версии.') from e
    if line!='ContractPrintApp '+version:
        raise ValueError('Версия готовой сборки не совпадает с номером обновления.')


def unpack_checked(archive, target):
    target = Path(target)
    with zipfile.ZipFile(archive) as z:
        if sum(i.file_size for i in z.infolist()) > MAX_ARCHIVE * 3:
            raise ValueError('Слишком большой размер распакованного обновления.')
        seen = set()
        for item in z.infolist():
            name = item.filename
            p = PurePosixPath(name)
            key = name.rstrip('/').casefold()
            if (not name or '\\' in name or ':' in name or p.is_absolute()
                    or '..' in p.parts or key in seen
                    or stat.S_ISLNK(item.external_attr >> 16)
                    or not (target / name).resolve().is_relative_to(target.resolve())):
                raise ValueError('Небезопасный путь в ZIP обновления.')
            if any(part.endswith((' ', '.')) for part in p.parts):
                raise ValueError('Недопустимое имя файла Windows в ZIP.')
            if any(re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I) for part in p.parts):
                raise ValueError('Зарезервированное имя файла Windows в ZIP.')
            seen.add(key)
        z.extractall(target)
    if not (target / 'ContractPrintApp.exe').is_file() or not (target / '_internal').is_dir():
        raise ValueError('Нужен ZIP готовой Windows-сборки, а не исходников.')


def stage_update(info, install):
    if info.get('product') != 'ContractPrintApp':
        raise ValueError('Этот пакет предназначен для другого приложения.')
    install = Path(install).resolve()
    stage = Path(tempfile.mkdtemp(prefix='.' + install.name + '-stage-', dir=install.parent))
    try:
        archive = stage / 'payload.zip'
        with Path(info['path']).open('rb') as src, archive.open('wb') as dst:
            size = 0
            for chunk in iter(lambda: src.read(1024 * 1024), b''):
                size += len(chunk)
                if size > MAX_ARCHIVE:
                    raise ValueError('Архив обновления больше 1 ГБ.')
                dst.write(chunk)
        if digest(archive) != info['sha256'].lower():
            raise ValueError('Контрольная сумма обновления не совпала. Установка отменена.')
        content = stage / 'app'
        content.mkdir()
        unpack_checked(archive, content)
        check_bundle_version(content, info['version'])
        return content
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


class InstallLock:
    """Each running EXE holds a shared lock; replacement takes an exclusive one."""
    def __init__(self, install, exclusive=False):
        self.path = Path(install).parent / ('.' + Path(install).name + '.update.lock')
        self.exclusive = exclusive
        self.stream = None

    def acquire(self):
        if not self.path.exists():
            try:
                with self.path.open('xb') as initial:initial.write(b'0')
            except FileExistsError:pass
        stream = self.path.open('r+b' if self.exclusive else 'rb')
        try:
            stream.seek(0)
            if os.name == 'nt':
                # CRT _locking treats the "read" variants as exclusive on
                # Windows. Use native shared byte locks, also supported by SMB.
                import ctypes
                from ctypes import wintypes as w
                import msvcrt
                class Overlapped(ctypes.Structure):
                    _fields_=[('Internal',ctypes.c_size_t),('InternalHigh',ctypes.c_size_t),
                              ('Offset',w.DWORD),('OffsetHigh',w.DWORD),('hEvent',w.HANDLE)]
                kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                kernel.LockFileEx.argtypes=[w.HANDLE,w.DWORD,w.DWORD,w.DWORD,w.DWORD,ctypes.POINTER(Overlapped)]
                kernel.LockFileEx.restype=w.BOOL
                self._overlapped=Overlapped()
                flags=1 | (2 if self.exclusive else 0)  # FAIL_IMMEDIATELY / EXCLUSIVE_LOCK
                if not kernel.LockFileEx(msvcrt.get_osfhandle(stream.fileno()),flags,0,1,0,ctypes.byref(self._overlapped)):
                    raise ctypes.WinError(ctypes.get_last_error())
            else:
                import fcntl
                fcntl.flock(stream, (fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except Exception:
            stream.close()
            raise
        self.stream = stream
        return self

    def close(self):
        if self.stream:
            self.stream.close(); self.stream = None


def replace_install(install, content, validate):
    """Caller must hold the exclusive lock. Preserve extra local files and rollback."""
    install, content = Path(install), Path(content)
    # Keep documented portable data directories; profile settings already live
    # outside the installation. Packaged settings are never accepted.
    for name in ('settings.json', 'userdata', 'user-data'):
        if (content / name).exists():
            raise ValueError('Обновление не должно содержать пользовательские настройки.')
        if (install / name).exists():
            src, dst = install / name, content / name
            if src.is_dir():shutil.copytree(src, dst)
            else:shutil.copy2(src, dst)
    backup = Path(tempfile.mkdtemp(prefix='.' + install.name + '-previous-', dir=install.parent))
    backup.rmdir()
    install.rename(backup)
    try:
        content.rename(install)
        validate(install)
    except Exception:
        if install.exists():shutil.rmtree(install)
        backup.rename(install)
        raise
    # Keep the previous version until the next explicit publishing/maintenance
    # action, so a successful update still has a recoverable backup.
    return backup


def launch_helper(content, install):
    if not getattr(sys, 'frozen', False) or sys.platform != 'win32':
        raise ValueError('Автоустановка доступна в готовой Windows-сборке.')
    helper = Path(tempfile.mkdtemp(prefix='ContractPrintApp-updater-'))
    shutil.copytree(install, helper / 'runner')
    plan = helper / 'plan.json'
    plan.write_text(json.dumps({'install': str(install), 'content': str(content)}), encoding='utf-8')
    subprocess.Popen([str(helper / 'runner' / 'ContractPrintApp.exe'), '--apply-update', str(plan)],
                     cwd=helper, close_fds=True)


def apply_plan(plan):
    plan = Path(plan)
    data = json.loads(plan.read_text(encoding='utf-8'))
    install, content = Path(data['install']).resolve(), Path(data['content']).resolve()
    if content.parent.parent != install.parent or not content.parent.name.startswith('.' + install.name + '-stage-'):
        raise ValueError('Некорректный каталог подготовленного обновления.')
    lock = InstallLock(install, exclusive=True)
    deadline = time.monotonic() + 300
    while True:
        try:
            lock.acquire(); break
        except OSError:
            if time.monotonic() > deadline:
                raise TimeoutError('Закройте ContractPrintApp на всех ПК и повторите обновление.')
            time.sleep(.5)
    def validate(folder):
        report = plan.parent / 'self-test.json'
        result = subprocess.run([str(folder / 'ContractPrintApp.exe'), '--self-test', str(report)],
                                cwd=plan.parent, timeout=90)
        if result.returncode or json.loads(report.read_text(encoding='utf-8')).get('status') != 'ok':
            raise RuntimeError('Новая версия не прошла самопроверку; восстановлена прежняя версия.')
    try:
        replace_install(install, content, validate)
    finally:
        lock.close()
    shutil.rmtree(content.parent, ignore_errors=True)
    subprocess.Popen([str(install / 'ContractPrintApp.exe')], cwd=install)


def publish(folder, output, version):
    """Publish locally, update-ContractPrintApp.json last. No network upload or credentials."""
    version_tuple(version)
    folder, output = Path(folder), Path(output)
    if not (folder / 'ContractPrintApp.exe').is_file() or not (folder / '_internal').is_dir():
        raise ValueError('Укажите папку готовой сборки dist/ContractPrintApp.')
    check_bundle_version(folder, version)
    output.mkdir(parents=True, exist_ok=True)
    name = 'ContractPrintApp-' + version + '-update.zip'
    archive = output / name
    if archive.exists():raise FileExistsError('Эта версия уже опубликована. Используйте новый номер версии.')
    fd, tmp = tempfile.mkstemp(suffix='.zip', dir=output);os.close(fd)
    try:
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in folder.rglob('*'):
                rel = p.relative_to(folder)
                if p.is_symlink():raise ValueError('Ссылки не допускаются в сборке.')
                if rel.parts[0] in ('settings.json', 'userdata', 'user-data'):continue
                if p.is_file():z.write(p, rel.as_posix())
        os.replace(tmp, archive)
        manifest = {'product':'ContractPrintApp', 'version': version, 'archive': name, 'sha256': digest(archive)}
        fd, meta = tempfile.mkstemp(suffix='.json', dir=output)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        os.replace(meta, output / 'update-ContractPrintApp.json')
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return archive


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Подготовка обновления для закрытой сетевой папки')
    parser.add_argument('build');parser.add_argument('share');parser.add_argument('version')
    args = parser.parse_args()
    print(publish(args.build, args.share, args.version))
