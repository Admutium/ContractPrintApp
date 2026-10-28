@echo off
chcp 65001 >nul
setlocal
pushd "%~dp0"
set "PYTHONUTF8=1"
echo ContractPrintApp - Windows build for the current user. No administrator rights required.
py -3.14 -c "import sys; sys.exit(0)" >nul 2>&1
if not errorlevel 1 (
  py -3.14 build_windows_App.py
  goto done
)
py -3.13 -c "import sys; sys.exit(0)" >nul 2>&1
if not errorlevel 1 (
  py -3.13 build_windows_App.py
  goto done
)
py -3.12 -c "import sys; sys.exit(0)" >nul 2>&1
if not errorlevel 1 (
  py -3.12 build_windows_App.py
  goto done
)
py -3.11 -c "import sys; sys.exit(0)" >nul 2>&1
if not errorlevel 1 (
  py -3.11 build_windows_App.py
  goto done
)
python -c "import sys; sys.exit(not ((3,11) <= sys.version_info[:2] <= (3,14)))" >nul 2>&1
if not errorlevel 1 (
  python build_windows_App.py
  goto done
)
echo Install Python 3.11, 3.12, 3.13 or 3.14 x64 for the CURRENT USER, then run this file again.
:done
popd
pause
