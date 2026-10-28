"""Probe the actual build interpreter; explicitly locate Tk files for freezing."""
import json,sys
from pathlib import Path

def collect():
    import _tkinter
    import tkinter as tk
    root=tk.Tk();root.withdraw()
    try:
        tcl=Path(root.tk.eval('info library')).resolve()
        tkdir=Path(root.tk.eval('set tk_library')).resolve()
        version=root.tk.eval('info patchlevel')
    finally:root.destroy()
    extension=Path(_tkinter.__file__).resolve()
    if not extension.is_file() or not (tcl/'init.tcl').is_file() or not (tkdir/'tk.tcl').is_file():
        raise RuntimeError('Tkinter imports but its extension or Tcl/Tk data files are missing.')
    binaries=[(str(extension),'.')]
    dlls={}
    for directory in [extension.parent,Path(sys.base_prefix)/'DLLs',Path(sys.base_prefix)]:
        if directory.is_dir():
            for path in directory.glob('*.dll'):
                if path.name.lower().startswith(('tcl8','tk8','tcl9','tk9')):dlls.setdefault(path.name.lower(),path.resolve())
    if sys.platform=='win32' and not (any(n.startswith('tcl') for n in dlls) and any(n.startswith('tk') for n in dlls)):
        raise RuntimeError('Tcl/Tk DLL files were not found next to the installed Python. Repair the Tcl/Tk component of Python.')
    binaries.extend((str(path),'.') for path in dlls.values())
    data=[(str(tcl),'_tcl_data'),(str(tkdir),'_tk_data')]
    shared=tcl.parent/'tcl8'
    if shared.is_dir():data.append((str(shared),'tcl8'))
    return {'python':sys.executable,'extension':str(extension),'tcl_version':version,'binaries':binaries,'data':data}

if __name__=='__main__':
    output=Path(sys.argv[1])
    output.write_text(json.dumps(collect(),ensure_ascii=False,indent=2),encoding='utf-8')
