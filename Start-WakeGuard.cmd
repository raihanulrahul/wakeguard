@echo off
setlocal
cd /d "%~dp0"
set "WG_PY=%~dp0.venv_wakeguard\Scripts\pythonw.exe"
if not exist "%WG_PY%" (
  echo Run Setup-WakeGuard-Private.ps1 first. Existing system Python is not used.
  pause
  exit /b 1
)
start "" "%WG_PY%" -E -s -B "%~dp0wakeguard_launcher.pyw" %*
endlocal
