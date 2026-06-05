@echo off
cd /d "%~dp0"
set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%PYTHON_EXE%" (
  "%PYTHON_EXE%" app.py
) else (
  python app.py
)
pause
