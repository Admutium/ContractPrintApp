"""Small ZIP checks; accepts a local, mapped-drive or SMB destination."""
from pathlib import Path
import sys
import tempfile
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from updater import unpack_checked


def main(folder):
    root=Path(folder);root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='App-zip-check-',dir=root) as tmp:
        base=Path(tmp)
        for index,separator in enumerate(('/','\\')):
            archive=base/('good-'+str(index)+'.zip')
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr(separator.join(('ContractPrintApp','ContractPrintApp.exe')),b'demo')
                z.writestr(separator.join(('ContractPrintApp','_internal','demo.dll')),b'demo')
            target=base/('good-'+str(index))
            unpack_checked(archive,target)
            assert (target/'ContractPrintApp.exe').read_bytes()==b'demo'
        for index,name in enumerate(('../escape','..\\escape','/absolute','\\absolute','C:/escape','CON.txt','file. ')):
            archive=base/('bad-'+str(index)+'.zip')
            with zipfile.ZipFile(archive,'w') as z:z.writestr(name,b'bad')
            try:unpack_checked(archive,base/('bad-'+str(index)))
            except ValueError:pass
            else:raise AssertionError('Unsafe member accepted')
        archive=base/'conflict.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('a/b',b'first');z.writestr('a\\b',b'second')
        try:unpack_checked(archive,base/'conflict')
        except ValueError:pass
        else:raise AssertionError('Normalized duplicate accepted')
    print('ZIP: Windows separators, product wrapper and traversal protections verified on '+str(root))


if __name__=='__main__':main(sys.argv[1])
