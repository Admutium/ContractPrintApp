"""Application icon and stable Windows taskbar identity."""
from pathlib import Path
import sys

ASSETS = Path(__file__).resolve().parent / 'assets'


def set_taskbar_identity():
    if sys.platform == 'win32':
        import ctypes
        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('ContractPrintApp.Desktop')
        if result:
            raise OSError('Не удалось задать идентификатор панели задач ContractPrintApp.')


def set_window_icon(root):
    if sys.platform == 'win32':
        path = str(ASSETS / 'ContractPrintApp.ico')
        root.iconbitmap(default=path)
        root.iconbitmap(path)
    else:
        import tkinter as tk
        root._app_icon = tk.PhotoImage(file=str(ASSETS / 'ContractPrintApp.png'))
        root.iconphoto(True, root._app_icon)
