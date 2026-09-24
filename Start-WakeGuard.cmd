@echo off
setlocal
cd /d "%~dp0"
set "PYTHONDONTWRITEBYTECODE=1"
set "WG_PY=%~dp0.venv_wakeguard\Scripts\python.exe"
if not exist "%WG_PY%" (
  echo Run Setup-WakeGuard.ps1 first. Existing old environments are not used.
  pause
  exit /b 1
)
"%WG_PY%" -B "%~dp0mvsa_app.py" %*
if errorlevel 1 (
  echo WakeGuard exited with an error. Run scripts\doctor.py in the vision environment.
  pause
  exit /b 1
)
endlocal
