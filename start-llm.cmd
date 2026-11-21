@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem Usage: start-llm.cmd [gpu_layers]
rem Lower the layer count if F1 24 stutters or the model crashes (VRAM pressure).
set NGL=%1
if "%NGL%"=="" set NGL=24

set MODEL=
for %%f in ("models\llm\qwen2.5-7b-instruct-q4_k_m*.gguf") do (
  if not defined MODEL set MODEL=%%~f
)

if not exist "models\llama\llama-server.exe" (
  echo llama.cpp not found. Run:
  echo   powershell -ExecutionPolicy Bypass -File setup.ps1 -Models
  exit /b 1
)
if not defined MODEL (
  echo Model not found. Run:
  echo   powershell -ExecutionPolicy Bypass -File setup.ps1 -Models
  exit /b 1
)

echo Loading !MODEL!
"models\llama\llama-server.exe" ^
  -m "!MODEL!" ^
  -c 4096 ^
  -ngl %NGL% ^
  --host 127.0.0.1 ^
  --port 8080 ^
  --jinja ^
  -t 8
