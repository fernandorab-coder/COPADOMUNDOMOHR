@echo off
cd /d "%~dp0"
set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%PYTHON_EXE%" (
  start "Bolao Copa 2026" /min "%PYTHON_EXE%" app.py
) else (
  start "Bolao Copa 2026" /min python app.py
)

timeout /t 2 /nobreak >nul
start http://localhost:3000
