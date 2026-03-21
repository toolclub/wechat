w@echo off
title LLM Chat - Start

echo ============================================
echo   LLM Chat Start Script
echo ============================================
echo.

REM -- Paths relative to this script's directory --
set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%llm-chat\backend"
set "FRONTEND_DIR=%PROJECT_ROOT%llm-chat\frontend"
set "CLOUDFLARED=%PROJECT_ROOT%cloudflared.exe"
set "LOG_ROOT=D:\app\ChatFlow"

REM -- Check if already running --
tasklist /FI "WINDOWTITLE eq LLM-Backend" 2>nul | findstr "cmd.exe" >nul
if %errorlevel%==0 (
    echo [WARN] Services already running. Run stop.bat first.
    pause
    exit /b 1
)

REM -- Create log directories --
if not exist "%LOG_ROOT%" mkdir "%LOG_ROOT%"
if not exist "%LOG_ROOT%\backend" mkdir "%LOG_ROOT%\backend"
if not exist "%LOG_ROOT%\frontend" mkdir "%LOG_ROOT%\frontend"

REM -- Check venv exists --
if not exist "%BACKEND_DIR%\venv\Scripts\activate.bat" (
    echo [ERROR] Python venv not found: %BACKEND_DIR%\venv
    echo Run: cd /d %BACKEND_DIR% ^&^& python -m venv venv ^&^& venv\Scripts\activate ^&^& pip install -e .
    pause
    exit /b 1
)

REM -- 1. Install backend dependencies --
echo [1/4] Installing backend dependencies...
call "%BACKEND_DIR%\venv\Scripts\pip.exe" install -e "%BACKEND_DIR%" --quiet
if %errorlevel% neq 0 (
    echo [ERROR] pip install failed, check network or venv.
    pause
    exit /b 1
)

REM -- 2. Start backend --
echo [2/4] Starting backend FastAPI :8000 ...
start "LLM-Backend" cmd /k "cd /d %BACKEND_DIR% && call venv\Scripts\activate && python main.py >> %LOG_ROOT%\backend\backend.log 2>&1"

echo     Waiting for backend...
timeout /t 4 /nobreak > nul

REM -- 2. Start frontend --
echo [3/4] Starting frontend Vue3/Vite :80 ...
start "LLM-Frontend" cmd /k "cd /d %FRONTEND_DIR% && npm run dev >> %LOG_ROOT%\frontend\frontend.log 2>&1"

echo     Waiting for frontend...
timeout /t 8 /nobreak > nul

REM -- 3. Start Cloudflare tunnel --
echo [4/4] Starting Cloudflare tunnel...
start "LLM-Cloudflared" cmd /k "%CLOUDFLARED% tunnel --url http://localhost:80 >> %LOG_ROOT%\cloudflared.log 2>&1"

echo.
echo ============================================
echo   All services started!
echo ============================================
echo.
echo   Local:    http://localhost
echo   API docs: http://localhost:8000/docs
echo   Public URL: check %LOG_ROOT%\cloudflared.log
echo.
echo   Logs:
echo     Backend:    %LOG_ROOT%\backend\backend.log
echo     Frontend:   %LOG_ROOT%\frontend\frontend.log
echo     Tunnel:     %LOG_ROOT%\cloudflared.log
echo.
echo   Run stop.bat to shut down all services.
echo ============================================
pause
