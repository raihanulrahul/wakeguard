@echo off
setlocal
cd /d "%~dp0"
echo Close WakeGuard before updating. Local source changes are protected.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-WakeGuard.ps1" -Destination "%~dp0." -Update
if errorlevel 1 (
  echo Update stopped. Read the error above; no forced reset is performed.
  pause
  exit /b 1
)
endlocal
