@echo off
setlocal
cd /d "%~dp0"

if not exist config.yaml (
  if exist config.example.yaml copy config.example.yaml config.yaml >nul
)

if "%BACKEND_PORT%"=="" set BACKEND_PORT=8010
if "%BACKEND_HOST%"=="" set BACKEND_HOST=127.0.0.1
set APP_URL=http://%BACKEND_HOST%:%BACKEND_PORT%/

where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js/npm is required. Please install Node.js LTS first.
  pause
  exit /b 1
)

where uv >nul 2>nul
if errorlevel 1 goto install_uv
set "UV_CMD=uv"
echo [TinyWorld] Using installed uv.
goto have_uv

:install_uv
echo [TinyWorld] Installing uv...
set "UV_BOOTSTRAP="
where python >nul 2>nul
if not errorlevel 1 (
  python -m pip install -U uv
  if not errorlevel 1 (
    set "UV_BOOTSTRAP=python"
    goto uv_installed
  )
)

where py >nul 2>nul
if not errorlevel 1 (
  py -m pip install -U uv
  if not errorlevel 1 (
    set "UV_BOOTSTRAP=py"
    goto uv_installed
  )
)

echo Python 3.11+ is required. Please install Python first, or install uv and make sure uv is in PATH.
pause
exit /b 1

:uv_installed
where uv >nul 2>nul
if errorlevel 1 (
  set "UV_CMD=%UV_BOOTSTRAP% -m uv"
) else (
  set "UV_CMD=uv"
)

:have_uv
%UV_CMD% --version
if errorlevel 1 (
  pause
  exit /b 1
)

echo [TinyWorld] Installing Python dependencies...
%UV_CMD% sync
if errorlevel 1 (
  pause
  exit /b 1
)

echo [TinyWorld] Installing frontend dependencies...
call npm --prefix frontend install
if errorlevel 1 (
  pause
  exit /b 1
)

echo [TinyWorld] Building frontend...
call npm --prefix frontend run build
if errorlevel 1 (
  pause
  exit /b 1
)

echo [TinyWorld] Starting backend at %APP_URL%
start "" "%APP_URL%"
%UV_CMD% run uvicorn app.main:app --app-dir backend --host %BACKEND_HOST% --port %BACKEND_PORT%
pause
