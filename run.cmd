@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Run:
  echo   powershell -ExecutionPolicy Bypass -File setup.ps1
  exit /b 1
)
".venv\Scripts\python.exe" -m app %*
