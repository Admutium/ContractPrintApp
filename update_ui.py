"""Tk integration; network-share I/O runs off the GUI thread."""
from pathlib import Path
import queue
import shutil
import sys
import threading
from tkinter import ttk
from dialogs import messagebox, filedialog, new_dialog
from updater import read_update, stage_update, launch_helper


class UpdateUI:
    def update_settings(self):
        folder = filedialog.askdirectory(title='Папка обновлений ContractPrintApp',
                                         initialdir=self.settings.get('update_folder', ''))
        if not folder:return
        self.settings['update_folder'] = folder
        self.remember()
        self.check_updates(manual=True)

    def disable_updates(self):
        self.settings.pop('update_folder', None)
        self.remember()
        self.status.set('Проверка обновлений отключена.')

    def check_updates(self, manual=False):
        from features import VERSION
        if getattr(self, '_update_busy', False):return
        folder = self.settings.get('update_folder')
        if not folder:
            if manual:self.update_settings()
            return
        self._update_busy = True
        self._run_update_task(lambda: read_update(folder, VERSION),
                              lambda value, error:self._update_checked(value, error, manual))

    def _run_update_task(self, work, done):
        results = queue.Queue()
        def run():
            try:results.put((work(), None))
            except Exception as e:results.put((None, e))
        threading.Thread(target=run, daemon=True).start()
        def poll():
            try:value, error = results.get_nowait()
            except queue.Empty:
                self.root.after(150, poll);return
            done(value, error)
        self.root.after(150, poll)

    def _update_checked(self, info, error, manual):
        self._update_busy = False
        if error:
            if manual:messagebox.showerror('Обновление', str(error))
            else:self.status.set('Папка обновлений недоступна. Текущая версия продолжает работать.')
            return
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
        self._run_update_task(lambda:stage_update(info, install), self._update_staged)

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
