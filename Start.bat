@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not exist config.yaml (
  if exist config.example.yaml copy config.example.yaml config.yaml >nul
)

if "%BACKEND_PORT%"=="" set BACKEND_PORT=8010
if "%BACKEND_HOST%"=="" set BACKEND_HOST=127.0.0.1
if "%FRONTEND_PORT%"=="" set FRONTEND_PORT=5174
set APP_URL=http://%BACKEND_HOST%:%BACKEND_PORT%/

call :print_banner
call :stop_port "%BACKEND_PORT%"
call :stop_port "%FRONTEND_PORT%"
call :check_updates

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
exit /b

:print_banner
echo [TinyWorld] Running
echo Project: %CD%
echo URL:     %APP_URL%
echo.
echo Close this window to stop TinyWorld.
echo.
exit /b 0

:stop_port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%~1" ^| findstr "LISTENING"') do taskkill /PID %%a /F >nul 2>nul
exit /b 0

:check_updates
if /I "%AIWORLD_SKIP_UPDATE_CHECK%"=="1" exit /b 0
where git >nul 2>nul
if errorlevel 1 exit /b 0
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 exit /b 0
git remote get-url origin >nul 2>nul
if errorlevel 1 exit /b 0

set "GIT_BRANCH="
for /f "delims=" %%a in ('git branch --show-current 2^>nul') do set "GIT_BRANCH=%%a"
if "!GIT_BRANCH!"=="" exit /b 0

set "GIT_DIRTY="
for /f "delims=" %%a in ('git status --porcelain --untracked-files^=no 2^>nul') do (
  set "GIT_DIRTY=1"
  goto check_updates_status_done
)
:check_updates_status_done
if "!GIT_DIRTY!"=="1" (
  echo [TinyWorld] Local tracked files have uncommitted changes; skipping GitHub update check.
  exit /b 0
)

echo [TinyWorld] Checking GitHub for updates (metadata only; files are not changed).
set "GIT_TERMINAL_PROMPT=0"
where powershell >nul 2>nul
if errorlevel 1 (
  git -c http.lowSpeedLimit=1 -c http.lowSpeedTime=8 fetch --quiet origin
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = Start-Process -FilePath 'git' -ArgumentList @('-c','http.lowSpeedLimit=1','-c','http.lowSpeedTime=8','fetch','--quiet','origin') -NoNewWindow -PassThru; if (-not $p.WaitForExit(10000)) { try { $p.Kill() } catch {}; exit 124 }; exit $p.ExitCode"
)
if errorlevel 1 (
  echo [TinyWorld] Update check failed or timed out; continuing startup.
  exit /b 0
)

set "REMOTE_REF=origin/!GIT_BRANCH!"
git rev-parse --verify "!REMOTE_REF!" >nul 2>nul
if errorlevel 1 exit /b 0

set "LOCAL_HEAD="
set "REMOTE_HEAD="
set "MERGE_BASE="
for /f "delims=" %%a in ('git rev-parse HEAD 2^>nul') do set "LOCAL_HEAD=%%a"
for /f "delims=" %%a in ('git rev-parse "!REMOTE_REF!" 2^>nul') do set "REMOTE_HEAD=%%a"
if "!LOCAL_HEAD!"=="" exit /b 0
if "!REMOTE_HEAD!"=="" exit /b 0
if "!LOCAL_HEAD!"=="!REMOTE_HEAD!" (
  echo [TinyWorld] Local version matches GitHub; no update needed.
  exit /b 0
)

for /f "delims=" %%a in ('git merge-base HEAD "!REMOTE_REF!" 2^>nul') do set "MERGE_BASE=%%a"
if "!MERGE_BASE!"=="!REMOTE_HEAD!" (
  echo [TinyWorld] Local version is ahead of GitHub; no update needed.
  exit /b 0
)
if not "!MERGE_BASE!"=="!LOCAL_HEAD!" (
  echo [TinyWorld] GitHub has changes, but local history differs; skipping automatic update.
  exit /b 0
)

echo [TinyWorld] GitHub has updates.
set "UPDATE_ANSWER="
set /p "UPDATE_ANSWER=Update before startup? [y/N] "
if /I "!UPDATE_ANSWER!"=="Y" (
  git pull --ff-only
  if errorlevel 1 (
    echo [TinyWorld] Update failed; continuing startup without updating.
  ) else (
    echo [TinyWorld] Update complete; continuing startup.
  )
) else (
  echo [TinyWorld] Update skipped; continuing startup.
)
exit /b 0
