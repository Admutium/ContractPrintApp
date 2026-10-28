"""Owned, centered dialogs with monitor-aware bounds; native file pickers keep OS layout."""
import sys,tkinter as tk
from tkinter import ttk,filedialog as native_files
from tkinter.scrolledtext import ScrolledText


def work_area(parent):
    if sys.platform=='win32':
        try:
            import ctypes
            from ctypes import wintypes as w
            class Info(ctypes.Structure):
                _fields_=[('size',w.DWORD),('monitor',w.RECT),('work',w.RECT),('flags',w.DWORD)]
            user=ctypes.windll.user32
            user.MonitorFromWindow.argtypes=[w.HWND,w.DWORD];user.MonitorFromWindow.restype=w.HANDLE
            user.GetMonitorInfoW.argtypes=[w.HANDLE,ctypes.POINTER(Info)]
            info=Info();info.size=ctypes.sizeof(info)
            if user.GetMonitorInfoW(user.MonitorFromWindow(parent.winfo_id(),2),ctypes.byref(info)):
                r=info.work;return r.left,r.top,r.right,r.bottom
        except (OSError,AttributeError,ValueError):pass
    x,y=parent.winfo_vrootx(),parent.winfo_vrooty()
    return x,y,x+parent.winfo_vrootwidth(),y+parent.winfo_vrootheight()


def centered_rect(parent_rect,area,width,height):
    left,top,right,bottom=area
    width=min(width,max(100,right-left-24));height=min(height,max(100,bottom-top-48))
    px,py,pw,ph=parent_rect
    x=max(left+12,min(px+(pw-width)//2,right-width-12))
    y=max(top+12,min(py+(ph-height)//2,bottom-height-36))
    return width,height,x,y


def center_window(win,parent):
    if not win.winfo_exists():return
    win.update_idletasks();parent.update_idletasks()
    width,height=getattr(win,'_preferred_size',(win.winfo_reqwidth(),win.winfo_reqheight()))
    width,height,x,y=centered_rect((parent.winfo_rootx(),parent.winfo_rooty(),parent.winfo_width(),parent.winfo_height()),work_area(parent),width,height)
    win.geometry(f'{width}x{height}{max(0,x):+d}{max(0,y):+d}');win.deiconify();win.update_idletasks()
    if sys.platform=='win32':
        try:
            import ctypes
            from ctypes import wintypes as w
            user=ctypes.windll.user32
            user.GetAncestor.argtypes=[w.HWND,w.UINT];user.GetAncestor.restype=w.HWND
            user.SetWindowPos.argtypes=[w.HWND,w.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.UINT]
            # SWP_NOSIZE | SWP_NOZORDER; actual screen coordinates also work on a monitor left of primary.
            user.SetWindowPos(user.GetAncestor(win.winfo_id(),2),None,x,y,0,0,0x0001|0x0004)
        except (OSError,AttributeError,ValueError):pass
    win.grab_set();win.lift()


def new_dialog(parent,title,width=700,height=460):
    win=tk.Toplevel(parent);win.withdraw();win.title(title);win.transient(parent)
    win._preferred_size=(width,height)
    win.geometry(f'{width}x{height}')
    win.after_idle(lambda:center_window(win,parent))
    return win


def scroll_body(win,padding=12):
    area=ttk.Frame(win);area.pack(fill='both',expand=True)
    canvas=tk.Canvas(area,highlightthickness=0);scroll=ttk.Scrollbar(area,command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
    body=ttk.Frame(canvas,padding=padding);window=canvas.create_window(0,0,window=body,anchor='nw')
    body.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
    canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
    def wheel(e):
        widget=e.widget
        while widget is not None:
            if widget==body or widget==canvas:
                canvas.yview_scroll(-3 if e.delta>0 else 3,'units');return 'break'
            widget=getattr(widget,'master',None)
    win.bind('<MouseWheel>',wheel)
    return area,body


class Messages:
    def _show(self,title,message,kind='info',parent=None,**kwargs):
        parent=parent or tk._default_root
        if parent is None:raise RuntimeError('Нет главного окна для сообщения')
        win=new_dialog(parent,title,620,min(360,parent.winfo_screenheight()-100));result=[None]
        buttons=ttk.Frame(win,padding=12);buttons.pack(side='bottom',fill='x')
        box=ScrolledText(win,wrap='word',height=8,padx=12,pady=12,font=('Segoe UI' if sys.platform=='win32' else 'DejaVu Sans',10))
        box.pack(fill='both',expand=True,padx=10,pady=(10,0));box.insert('1.0',str(message));box.configure(state='disabled')
        def choose(value):
            if win.winfo_exists():result[0]=value;win.destroy()
        choices=[('ОК','ok')] if kind=='info' else [('Да',True),('Нет',False)]+([('Отмена',None)] if kind=='cancel' else [])
        focus=None
        for label,value in choices:
            button=ttk.Button(buttons,text=label,command=lambda v=value:choose(v));button.pack(side='left',padx=5)
            if label in ('ОК','Нет'):focus=button
        win.protocol('WM_DELETE_WINDOW',lambda:choose(None if kind=='cancel' else False if kind=='question' else 'ok'))
        win.bind('<Escape>',lambda e:choose(None if kind=='cancel' else False if kind=='question' else 'ok'))
        win.after_idle(lambda:focus.focus_set() if focus and win.winfo_exists() else None)
        def accept(event):
            if win.winfo_exists():
                (event.widget if isinstance(event.widget,ttk.Button) else focus).invoke()
            return 'break'
        # Handle Return before ttk's class binding; otherwise a focused button
        # can be invoked twice, including after its dialog has been destroyed.
        win.bind('<Return>',accept)
        for child in buttons.winfo_children():child.bind('<Return>',accept)
        previous=parent.grab_current()
        parent.wait_window(win)
        if previous and previous.winfo_exists():previous.grab_set()
        return result[0]
    def showinfo(self,title,message,**kw):return self._show(title,message,**kw)
    showwarning=showerror=showinfo
    def askyesno(self,title,message,**kw):return self._show(title,message,kind='question',**kw)
    def askyesnocancel(self,title,message,**kw):return self._show(title,message,kind='cancel',**kw)

class Files:
    def __getattr__(self,name):
        def call(*args,**kwargs):
            kwargs.setdefault('parent',tk._default_root)
            return getattr(native_files,name)(*args,**kwargs)
        return call

messagebox=Messages();filedialog=Files()
