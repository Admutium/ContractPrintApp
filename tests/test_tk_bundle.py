import os,runpy,sys,tempfile,types,unittest
from pathlib import Path
from unittest.mock import patch
import tk_bundle

class TkPackagingTests(unittest.TestCase):
    def test_probe_collects_extension_dlls_and_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);dlls=base/'DLLs';dlls.mkdir()
            ext=dlls/'_tkinter.pyd';ext.write_bytes(b'test fixture')
            for name in ('tcl86t.dll','tk86t.dll'):(dlls/name).write_bytes(b'test fixture')
            tcl=base/'tcl'/'tcl8.6';tkdir=base/'tcl'/'tk8.6';tcl.mkdir(parents=True);tkdir.mkdir()
            (tcl/'init.tcl').write_text('fixture');(tkdir/'tk.tcl').write_text('fixture');(tcl.parent/'tcl8').mkdir()
            class Root:
                def __init__(self):self.tk=self
                def withdraw(self):pass
                def destroy(self):pass
                def eval(self,command):return {'info library':str(tcl),'set tk_library':str(tkdir),'info patchlevel':'8.6.15'}[command]
            mods={'_tkinter':types.SimpleNamespace(__file__=str(ext)),'tkinter':types.SimpleNamespace(Tk=Root)}
            with patch.dict(sys.modules,mods),patch.object(sys,'platform','win32'),patch.object(sys,'base_prefix',str(base)):
                info=tk_bundle.collect()
                self.assertEqual({Path(p).name for p,_ in info['binaries']},{'_tkinter.pyd','tcl86t.dll','tk86t.dll'})
                self.assertEqual({d for _,d in info['data']},{'_tcl_data','_tk_data','tcl8'})
                (tkdir/'tk.tcl').unlink()
                with self.assertRaises(RuntimeError):tk_bundle.collect()
    def test_runtime_uses_bundle_and_rejects_missing_data(self):
        hook=Path(__file__).resolve().parents[1]/'runtime_tk.py'
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            for name in ('_tcl_data','_tk_data'):(base/name).mkdir()
            with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS',str(base),create=True),patch.dict(os.environ,{'TCL_LIBRARY':'external','TK_LIBRARY':'external'}):
                runpy.run_path(str(hook))
                self.assertEqual(os.environ['TCL_LIBRARY'],str(base/'_tcl_data'))
                self.assertEqual(os.environ['TK_LIBRARY'],str(base/'_tk_data'))
                (base/'_tk_data').rmdir()
                with self.assertRaises(RuntimeError):runpy.run_path(str(hook))
