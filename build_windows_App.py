"""One-time Windows build. All build dependencies live in the current user profile."""
import os,sys,subprocess,venv,shutil,platform,json,hashlib
from pathlib import Path
from datetime import datetime

def main():
    if sys.platform!='win32' or not (3,11)<=sys.version_info[:2]<=(3,14) or platform.architecture()[0]!='64bit':
        raise RuntimeError('Нужен Windows и Python 3.11–3.14, включая 3.14.3 (64-bit). Установите Python только для текущего пользователя.')
    source=Path(__file__).resolve().parent
    cache=source/'.build-App' # Temporary output; the reusable environment may live in LocalAppData.
    # Reuse a legacy project environment; otherwise use a shared user build cache.
    legacy=cache/f'python-{sys.version_info.major}{sys.version_info.minor}-tkfix1'
    shared=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ContractPrintBuildApp'
    env=legacy if (legacy/'Scripts/python.exe').is_file() else shared/f'python-{sys.version_info.major}{sys.version_info.minor}'
    py=env/'Scripts'/'python.exe'
    if not py.exists():venv.EnvBuilder(with_pip=True).create(env)
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S');work=cache/stamp;work.mkdir(parents=True,exist_ok=True)
    logfile=work/'build.log'
    def run(args):
        print('\n>',subprocess.list2cmdline([str(x) for x in args]),flush=True)
        with subprocess.Popen([str(x) for x in args],cwd=source,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONUTF8':'1'}) as process, logfile.open('a',encoding='utf-8') as log:
            for line in process.stdout:print(line,end='',flush=True);log.write(line)
            if process.wait():raise RuntimeError(f'Ошибка сборки. Журнал: {logfile}')
    # Probe the SAME interpreter used by PyInstaller before spending time building.
    probe=work/'tk-probe.json'
    run([py,source/'tk_bundle.py',probe])
    tkinfo=json.loads(probe.read_text(encoding='utf-8'))
    tkargs=['--hidden-import','tkinter','--hidden-import','_tkinter',
            '--runtime-hook',str(source/'runtime_tk.py')]
    for file,destination in tkinfo['binaries']:
        tkargs.extend(['--add-binary',file+';'+destination])
    for folder,destination in tkinfo['data']:
        tkargs.extend(['--add-data',folder+';'+destination])
    spec=hashlib.sha256((source/'requirements.txt').read_bytes()+(source/'requirements-build.txt').read_bytes()+sys.version.encode()).hexdigest()
    marker=env/'contractprintapp-dependencies.sha256'
    if not marker.exists() or marker.read_text('utf-8')!=spec:
        run([py,'-m','pip','install','-r',source/'requirements-build.txt'])
        run([py,'-m','pip','check'])
        marker.write_text(spec,encoding='utf-8')
    else:print('Зависимости уже подготовлены — повторная загрузка не требуется.',flush=True)
    run([py,'-m','unittest','discover','-s','tests','-p','test_app_variant.py','-v'])
    run([py,'-m','PyInstaller','--noconfirm','--clean','--windowed','--onedir','--noupx','--name','ContractPrintApp',
         '--distpath',work/'dist','--workpath',work/'work','--specpath',work,
         '--add-data',str(source/'assets')+';assets','--collect-all','tkinterdnd2',
         '--hidden-import','olefile','--hidden-import','PIL.ImageWin','--hidden-import','win32print','--hidden-import','win32gui','--hidden-import','win32ui','--hidden-import','win32con',*tkargs,source/'app.py'])
    built=work/'dist'/'ContractPrintApp'
    if not (built/'ContractPrintApp.exe').is_file():raise RuntimeError('EXE не создан. Проверьте журнал сборки.')
    internal=built/'_internal'
    if not list(internal.glob('_tkinter*.pyd')):
        raise RuntimeError('Проверка сборки: в EXE не включён модуль _tkinter. Журнал: '+str(logfile))
    for relative in ['_tcl_data/init.tcl','_tk_data/tk.tcl']:
        if not (internal/relative).is_file():raise RuntimeError('В сборке отсутствует '+relative)
    result=work/'self-test.json'
    # A successful PyInstaller build is not proof that the GUI can start.
    # Clear external Tcl/Python paths so the test uses the bundled components.
    testenv={k:v for k,v in os.environ.items() if k.upper() not in
             {'TCL_LIBRARY','TK_LIBRARY','TCLLIBPATH','PYTHONHOME','PYTHONPATH'}}
    try:
        proc=subprocess.run([str(built/'ContractPrintApp.exe'),'--self-test',str(result)],
                            cwd=work,env=testenv,timeout=60)
    except subprocess.TimeoutExpired:
        raise RuntimeError('EXE не завершил проверку запуска за 60 секунд. Проверьте окно ошибки и журнал: '+str(logfile))
    if not result.is_file():raise RuntimeError('EXE не создал отчёт проверки. Журнал: '+str(logfile))
    report=json.loads(result.read_text(encoding='utf-8'))
    if proc.returncode or report.get('status')!='ok':raise RuntimeError('Проверка EXE: '+report.get('error','процесс завершился с ошибкой')+'; отчёт: '+str(result))
    shutil.copy2(result,built/'SELF_TEST.json')
    shutil.copy2(probe,built/'TK_BUILD_INFO.json')
    freeze=subprocess.check_output([str(py),'-m','pip','freeze'],text=True,encoding='utf-8')
    (built/'BUILD_INFO.txt').write_text(f'ContractPrintApp 1.11.0\nBuilt: {stamp}\nPython: {sys.version}\n{freeze}',encoding='utf-8')
    for name in ['ИНСТРУКЦИЯ_App.txt','ПРОВЕРКА_App.txt','LICENSE.txt','ИЗМЕНЕНИЯ_1.11.0_App.txt','ОБНОВЛЕНИЯ_App.md']:
        if (source/name).exists():shutil.copy2(source/name,built/name)
    # The verified program is the one final folder. No file picker, ZIP copies or installer.
    final=source/'dist'/'ContractPrintApp'
    final.parent.mkdir(parents=True,exist_ok=True)
    previous=source/'dist'/'ContractPrintApp_previous'
    if previous.exists():shutil.rmtree(previous)
    if final.exists():final.rename(previous)
    try:
        shutil.move(str(built),str(final))
        final_result=source/'dist'/'FINAL_SELF_TEST.json'
        if final_result.exists():final_result.unlink()
        proc=subprocess.run([str(final/'ContractPrintApp.exe'),'--self-test',str(final_result)],cwd=source/'dist',env=testenv,timeout=90)
        if proc.returncode or not final_result.exists() or json.loads(final_result.read_text(encoding='utf-8')).get('status')!='ok':
            details=json.loads(final_result.read_text(encoding='utf-8')).get('error','') if final_result.exists() else 'Отчёт не создан'
            raise RuntimeError('Финальная проверка запуска: '+details+'; отчёт: '+str(final_result))
    except Exception:
        if final.exists():shutil.rmtree(final)
        if previous.exists():previous.rename(final)
        raise
    # Cleanup failure must not misreport a verified executable as a failed build.
    cleanup=[]
    def clean_folder(folder):
        try:shutil.rmtree(folder)
        except OSError:cleanup.append(str(folder))
    if previous.exists():clean_folder(previous)
    clean_folder(work)
    import re
    for old in cache.iterdir():
        if old.is_dir() and not old.is_symlink() and re.fullmatch(r'\d{8}-\d{6}',old.name):clean_folder(old)
    print('ГОТОВО:',final,'\nЗапуск: ContractPrintApp.exe\nПапку _internal не удалять.')
    if cleanup:print('Программа готова. Не удалось удалить временные папки:\n'+'\n'.join(dict.fromkeys(cleanup)))
if __name__=='__main__':
    try:main()
    except Exception as e:
        print('\nСБОРКА НЕ ЗАВЕРШЕНА:',e,flush=True)
        sys.exit(1)
