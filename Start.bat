@echo off
setlocal
cd /d "%~dp0"

if not exist config.yaml (
  if exist config.example.yaml copy config.example.yaml config.yaml >nul
)

if "%BACKEND_PORT%"=="" set BACKEND_PORT=8010
if "%BACKEND_HOST%"=="" set BACKEND_HOST=127.0.0.1
set APP_URL=http://%BACKEND_HOST%:%BACKEND_PORT%/

where py >nul 2>nul
if errorlevel 1 (
  echo Python is required. Please install Python 3.11+ first.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js/npm is required. Please install Node.js LTS first.
  pause
  exit /b 1
)

echo [TinyWorld] Installing uv...
py -m pip install -U uv
if errorlevel 1 (
  pause
  exit /b 1
)

echo [TinyWorld] Installing Python dependencies...
py -m uv sync
if errorlevel 1 (
  pause
  exit /b 1
)

echo [TinyWorld] Installing frontend dependencies...
npm --prefix frontend install
if errorlevel 1 (
  pause
  exit /b 1
)

echo [TinyWorld] Building frontend...
npm --prefix frontend run build
if errorlevel 1 (
  pause
  exit /b 1
)

echo [TinyWorld] Starting backend at %APP_URL%
start "" "%APP_URL%"
py -m uv run uvicorn app.main:app --app-dir backend --host %BACKEND_HOST% --port %BACKEND_PORT%
pause
