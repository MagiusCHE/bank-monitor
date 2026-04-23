@echo off
setlocal

cd /d "%~dp0"

if not exist .venv (
  python -m venv .venv
  if errorlevel 1 exit /b 1
  .venv\Scripts\python.exe -m pip install --upgrade pip wheel
  if errorlevel 1 exit /b 1
  .venv\Scripts\pip.exe install --only-binary=:all: -r requirements.txt
  if errorlevel 1 exit /b 1
)

if "%BANK_MONITOR_HOST%"=="" set BANK_MONITOR_HOST=0.0.0.0
if "%BANK_MONITOR_PORT%"=="" set BANK_MONITOR_PORT=8765

.venv\Scripts\python.exe -m uvicorn app.main:app --host %BANK_MONITOR_HOST% --port %BANK_MONITOR_PORT%

endlocal
