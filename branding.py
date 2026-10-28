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
        root._app_icon_path = path
    else:
        import tkinter as tk
        root._app_icon = tk.PhotoImage(file=str(ASSETS / 'ContractPrintApp.png'))
        root.iconphoto(True, root._app_icon)


def window_icon_state(root):
    """Inspect native icons: Windows Tk may return an empty wm iconbitmap name."""
    if sys.platform != 'win32':
        return {'configured':getattr(root,'_app_icon',None) is not None}
    import ctypes
    from ctypes import wintypes as w
    user = ctypes.windll.user32
    user.GetAncestor.argtypes = [w.HWND,w.UINT]
    user.GetAncestor.restype = w.HWND
    user.SendMessageW.argtypes = [w.HWND,w.UINT,w.WPARAM,w.LPARAM]
    user.SendMessageW.restype = ctypes.c_ssize_t
    hwnd = user.GetAncestor(root.winfo_id(),2)
    return {'configured':getattr(root,'_app_icon_path','').endswith('ContractPrintApp.ico'),
            'small_icon':bool(user.SendMessageW(hwnd,0x7F,0,0)),
            'big_icon':bool(user.SendMessageW(hwnd,0x7F,1,0))}
