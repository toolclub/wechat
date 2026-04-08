@echo off
title ChatFlow - Production Start
chcp 65001 > nul

echo ============================================
echo   ChatFlow Production Start (Windows)
echo   compose: docker-compose.prod.yml
echo   env:     .env.prod.win
echo ============================================
echo.

set "COMPOSE_DIR=%~dp0llm-chat"
set "ENV_FILE=%~dp0llm-chat\.env.prod.win"
set "CLOUDFLARED=%~dp0cloudflared.exe"
set "CLOUDFLARED_CONFIG=%~dp0cloudflared-config.yml"
set "CLOUDFLARED_LOG=%~dp0llm-chat\logs\cloudflared.log"

REM -- Check Docker is running --
docker info > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not running. Please start Docker Desktop first.
    pause
    exit /b 1
)

REM -- Check .env.prod.win exists --
if not exist "%ENV_FILE%" (
    echo [ERROR] .env.prod.win not found at: %ENV_FILE%
    pause
    exit /b 1
)

REM -- Create logs directory --
if not exist "%~dp0llm-chat\logs" mkdir "%~dp0llm-chat\logs"

echo [1/3] Building and starting production services...
cd /d "%COMPOSE_DIR%"
docker compose -f docker-compose.prod.yml --env-file .env --env-file .env.prod.win up -d --build
if %errorlevel% neq 0 (
    echo [ERROR] docker compose up failed.
    pause
    exit /b 1
)

echo.
echo [2/3] Waiting for services to become healthy...
timeout /t 10 /nobreak > nul
docker compose -f docker-compose.prod.yml ps

echo.
echo [3/3] Checking backend health...
timeout /t 5 /nobreak > nul
curl -sf http://localhost/api/tools > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Backend is healthy ^(8 Gunicorn workers running^).
) else (
    echo [WARN] Backend warming up. Run:
    echo   docker compose -f docker-compose.prod.yml logs -f backend
)

REM -- Start cloudflared as background process (no window) --
echo [4/4] Starting Cloudflare Tunnel...

if not exist "%CLOUDFLARED%" (
    echo [WARN] cloudflared.exe not found, skipping tunnel.
    goto :done
)

if not exist "%CLOUDFLARED_CONFIG%" (
    echo [WARN] cloudflared-config.yml not found, skipping tunnel.
    goto :done
)

REM -- Kill any existing cloudflared process first --
taskkill /f /im cloudflared.exe > nul 2>&1

REM -- Start silently in background, redirect output to log file --
start /b "" "%CLOUDFLARED%" tunnel --config "%CLOUDFLARED_CONFIG%" run >> "%CLOUDFLARED_LOG%" 2>&1

timeout /t 3 /nobreak > nul

tasklist | findstr /i "cloudflared.exe" > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Cloudflare Tunnel started ^(log: logs\cloudflared.log^)
) else (
    echo [ERROR] Cloudflare Tunnel failed to start. Check logs\cloudflared.log
)

:done
echo.
echo ============================================
echo   Production services started!
echo ============================================
echo.
echo   Frontend:  http://localhost
echo   API docs:  http://localhost:8000/docs
echo   Qdrant:    http://localhost:6333/dashboard
echo   Tunnel:    https://chatflow-live.com
echo.
echo   Worker count: 8 (GUNICORN_WORKERS in .env.prod.win)
echo.
echo   Useful commands:
echo     Logs:    docker compose -f llm-chat\docker-compose.prod.yml logs -f backend
echo     Status:  docker compose -f llm-chat\docker-compose.prod.yml ps
echo     Stop:    docker compose -f llm-chat\docker-compose.prod.yml down
echo ============================================
pause
