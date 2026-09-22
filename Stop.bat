@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Qwen Image Runner is not installed yet. Run Install.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\stop.py
timeout /t 2 >nul
