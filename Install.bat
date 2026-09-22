@echo off
setlocal
cd /d "%~dp0"
echo ==========================================
echo  Qwen Image Runner - Install
echo ==========================================
where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python 3.11 or newer is required.
  echo Install it from https://www.python.org/downloads/ and run this again.
  pause
  exit /b 1
)
python scripts\bootstrap.py
if errorlevel 1 (
  echo.
  echo Install failed. See the messages above.
  pause
  exit /b 1
)
echo.
echo Install finished. Start the app with Launch.bat
pause
