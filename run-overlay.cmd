@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Python environment missing. Run setup.ps1 first.
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m app.overlay --config config.yaml
