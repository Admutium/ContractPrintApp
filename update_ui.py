"""Tk integration; network-share I/O runs off the GUI thread."""
from pathlib import Path
import queue
import shutil
import sys
import threading
import time
from tkinter import ttk
from dialogs import messagebox, filedialog, new_dialog
from updater import read_update, stage_update, launch_helper
from github_updates import latest_update, download_update


class UpdateUI:
    def github_update_settings(self):
        self.settings['update_source']='github'
        self.settings['updates_enabled']=True
        self.remember();self.check_updates(manual=True)

    def update_settings(self):
        folder = filedialog.askdirectory(title='Папка обновлений ContractPrintApp',
                                         initialdir=self.settings.get('update_folder', ''))
        if not folder:return
        self.settings['update_folder'] = folder
        self.settings['update_source']='folder'
        self.settings['updates_enabled']=True
        self.remember()
        self.check_updates(manual=True)

    def disable_updates(self):
        self.settings['updates_enabled']=False
        self.remember()
        self.status.set('Проверка обновлений отключена.')

    def check_updates(self, manual=False):
        from features import VERSION
        if getattr(self, '_update_busy', False):return
        if not manual and not self.settings.get('updates_enabled',True):return
        source=self.settings.get('update_source','github')
        if source=='github':
            last=self.settings.get('github_checked_at',0)
            if (not manual and isinstance(last,(int,float)) and 0<=time.time()-last<21600
                    and self.settings.get('github_checked_version')==VERSION):return
            work=lambda:latest_update(VERSION)
        else:
            folder = self.settings.get('update_folder')
            if not folder:
                if manual:self.update_settings()
                return
            work=lambda:read_update(folder,VERSION)
        self._update_busy = True
        self._run_update_task(work,
                              lambda value, error:self._update_checked(value, error, manual))

    def _run_update_task(self, work, done, progress=None):
        results = queue.Queue()
        def run():
            try:results.put((work(), None))
            except Exception as e:results.put((None, e))
        threading.Thread(target=run, daemon=True).start()
        def poll():
            if progress is not None:
                try:
                    while True:self.status.set(progress.get_nowait())
                except queue.Empty:pass
            try:value, error = results.get_nowait()
            except queue.Empty:
                self.root.after(150, poll);return
            done(value, error)
        self.root.after(150, poll)

    def _update_checked(self, info, error, manual):
        self._update_busy = False
        if error:
            if manual:messagebox.showerror('Обновление', str(error))
            else:self.status.set('Проверка обновлений недоступна. Текущая версия продолжает работать.')
            return
        if self.settings.get('update_source','github')=='github':
            from features import VERSION
            self.settings['github_checked_at']=time.time()
            self.settings['github_checked_version']=VERSION
            self.remember()
        if info is None:
            if manual:messagebox.showinfo('Обновление', 'Установлена актуальная версия.')
            return
        if not getattr(sys, 'frozen', False) or sys.platform != 'win32':
            messagebox.showinfo('Обновление', 'Доступна версия '+info['version']+'. Автоустановка работает в готовой Windows-сборке, а не в исходниках.')
            return
        if not messagebox.askyesno('Обновление', 'Доступна версия '+info['version']+'. Подготовить обновление?\nПеред установкой нужно закрыть программу на остальных ПК, если она запускается из общей папки.'):
            return
        self._update_busy = True
        self.status.set('Подготовка обновления… Можно продолжать работу с карточкой.')
        install = Path(sys.executable).resolve().parent
        progress=queue.Queue()
        def prepare():
            if info.get('url'):
                def report(received,total):
                    progress.put('Скачивание обновления с GitHub: '+str(round(received*100/total))+' %')
                path=download_update(info,progress=report)
                return stage_update({**info,'path':str(path)},install)
            return stage_update(info,install)
        self._run_update_task(prepare, self._update_staged, progress)

    def _update_staged(self, content, error):
        self._update_busy = False
        if error:
            messagebox.showerror('Обновление', str(error));return
        if not messagebox.askyesno('Установка обновления', 'Обновление скачано и проверено. Закрыть программу и установить?\nСначала сохраните нужный PDF. Карточка между запусками не сохраняется.'):
            shutil.rmtree(content.parent, ignore_errors=True);return
        if not self.guard():
            shutil.rmtree(content.parent, ignore_errors=True);return
        try:
            self.remember()
            launch_helper(content, Path(sys.executable).resolve().parent)
        except Exception as e:
            shutil.rmtree(content.parent, ignore_errors=True)
            messagebox.showerror('Обновление', str(e));return
        self.clear_preview();self.root.destroy()
