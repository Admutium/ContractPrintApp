"""Exercise the actual frozen update helper on a Windows test machine."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from updater import InstallLock, publish, read_update, stage_update


def stop_executables(path):
    # Scope cleanup to the temporary fixture, never other ContractPrintApp users.
    env={**os.environ,'CONTRACTPRINTAPP_TEST_ROOT':str(path)}
    subprocess.run(['powershell','-NoProfile','-Command',
        'Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and '
        '$_.ExecutablePath.StartsWith($env:CONTRACTPRINTAPP_TEST_ROOT, '
        '[System.StringComparison]::OrdinalIgnoreCase) } | '
        'ForEach-Object { $p=Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue; '
        'if ($p) { $p | Stop-Process -Force -ErrorAction SilentlyContinue; '
        '$p | Wait-Process -Timeout 10 -ErrorAction SilentlyContinue } }'],
        env=env,check=True)


def main(build, previous=None):
    build=Path(build).resolve()
    with tempfile.TemporaryDirectory(prefix='ContractPrintApp-update-check-') as tmp:
        # Windows TEMP can use RUNNER~1 while Win32_Process reports the long
        # user path. Resolve aliases so scoped process cleanup finds the EXE.
        root=Path(tmp).resolve()
        install=root/'installed'/'ContractPrintApp'
        helper=root/'helper'
        candidate=root/'candidate'
        old_build=build
        if previous:
            unpack=root/'previous'
            with zipfile.ZipFile(previous) as z:
                for name in z.namelist():
                    if not (unpack/name).resolve().is_relative_to(unpack.resolve()):
                        raise ValueError('Unsafe previous archive')
                z.extractall(unpack)
            old_build=unpack/'ContractPrintApp'
        for path in (install,helper):shutil.copytree(old_build,path)
        shutil.copytree(build,candidate)
        (install/'package-marker.txt').write_text('old')
        (candidate/'package-marker.txt').write_text('new')
        (install/'user-data').mkdir()
        local_data=json.dumps({'firm_directory':[{'inn':'0'*10,'code':'DEMO','name':'Демонстрационная организация'}]})
        (install/'user-data'/'settings.json').write_text(local_data,encoding='utf-8')
        old_version=(install/'BUILD_INFO.txt').read_text(encoding='utf-8').splitlines()[0]
        version=(candidate/'BUILD_INFO.txt').read_text(encoding='utf-8').splitlines()[0].split()[-1]
        publish(candidate,root/'share',version)
        content=stage_update(read_update(root/'share','0.0.0'),install)
        plan=root/'plan.json'
        plan.write_text(json.dumps({'install':str(install),'content':str(content)}),encoding='utf-8')
        # An open program must delay replacement until all readers exit.
        lock=InstallLock(install).acquire()
        process=None
        try:
            env={**os.environ,'LOCALAPPDATA':str(root/'profile')}
            process=subprocess.Popen([str(helper/'ContractPrintApp.exe'),'--apply-update',str(plan)],cwd=root,env=env)
            time.sleep(2)
            assert process.poll() is None,'Helper exited while a running instance held the lock'
            assert (install/'package-marker.txt').read_text()=='old','Replaced a running installation'
            lock.close()
            assert process.wait(timeout=150)==0,'Frozen helper failed'
            assert (install/'package-marker.txt').read_text()=='new'
            assert (install/'user-data'/'settings.json').read_text(encoding='utf-8')==local_data
            report=json.loads((root/'self-test.json').read_text(encoding='utf-8'))
            assert report['status']=='ok',report
            backups=list(install.parent.glob('.ContractPrintApp-previous-*'))
            assert len(backups)==1
            assert (backups[0]/'package-marker.txt').read_text()=='old'
            print(old_version+' -> '+version+': lock wait, replacement, EXE self-test, local data and backup verified.')
        finally:
            lock.close()
            stop_executables(root)
            if process and process.poll() is None:process.wait(timeout=10)


if __name__=='__main__':main(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None)
