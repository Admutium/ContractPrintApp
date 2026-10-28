"""PyInstaller runtime hook: use Tcl/Tk bundled with this application."""
import os,sys
from pathlib import Path
if getattr(sys,'frozen',False):
    base=Path(sys._MEIPASS)
    for variable,folder in [('TCL_LIBRARY','_tcl_data'),('TK_LIBRARY','_tk_data')]:
        location=base/folder
        if not location.is_dir():raise RuntimeError('Incomplete application folder: '+str(location))
        os.environ[variable]=str(location)
