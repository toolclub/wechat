@echo off
title ChatFlow - Production Start
chcp 65001 > nul
pushd "%~dp0"

echo ============================================
echo   ChatFlow Production Start
echo ============================================
echo.

set "ROOT_DIR=%~dp0"
set "COMPOSE_DIR=%~dp0llm-chat"
set "SANDBOX_DIR=%~dp0llm-chat\sandbox"
set "ENV_FILE=%~dp0llm-chat\.env.prod.win"
set "CLOUDFLARED=%~dp0cloudflared.exe"
set "CLOUDFLARED_CONFIG=%~dp0cloudflared-config.yml"
set "CLOUDFLARED_LOG=%~dp0llm-chat\logs\cloudflared.log"

REM Check Docker
docker info > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not running. Please start Docker Desktop first.
    pause
    exit /b 1
)

REM Check env file
if not exist "%ENV_FILE%" (
    echo [ERROR] .env.prod.win not found at: %ENV_FILE%
    pause
    exit /b 1
)

if not exist "%~dp0llm-chat\logs" mkdir "%~dp0llm-chat\logs"

REM Step 1: Sandbox Cluster
echo [1/4] Starting Sandbox Cluster...
cd /d "%SANDBOX_DIR%"
docker compose --profile cluster up -d --build
if %errorlevel% neq 0 (
    echo [WARN] Cluster failed, trying standalone...
    docker compose --profile standalone up -d --build
    if %errorlevel% neq 0 (
        echo [WARN] Sandbox unavailable. Code execution disabled.
    ) else (
        echo [OK] Sandbox standalone started (port 2222)
    )
) else (
    echo [OK] Sandbox cluster started (ports 2222-2224)
)
echo.

REM Step 2: Main Services
echo [2/4] Starting main services...
cd /d "%COMPOSE_DIR%"
docker compose -f docker-compose.prod.yml --env-file .env --env-file .env.prod.win up -d --build
if %errorlevel% neq 0 (
    echo [ERROR] Main services failed to start.
    pause
    exit /b 1
)
echo.

REM Step 3: Health Check
echo [3/4] Waiting for services...
timeout /t 10 /nobreak > nul
docker compose -f docker-compose.prod.yml ps
echo.
curl -sf http://localhost/api/tools > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Backend is healthy.
) else (
    echo [WARN] Backend warming up. Run:
    echo   docker compose -f docker-compose.prod.yml logs -f backend
)
echo.

REM Step 4: Cloudflare Tunnel
echo [4/4] Starting Cloudflare Tunnel...
if not exist "%CLOUDFLARED%" (
    echo [SKIP] cloudflared.exe not found.
    goto done
)
if not exist "%CLOUDFLARED_CONFIG%" (
    echo [SKIP] cloudflared-config.yml not found.
    goto done
)
taskkill /f /im cloudflared.exe > nul 2>&1
start /b "" "%CLOUDFLARED%" tunnel --config "%CLOUDFLARED_CONFIG%" run >> "%CLOUDFLARED_LOG%" 2>&1
timeout /t 3 /nobreak > nul
tasklist | findstr /i "cloudflared.exe" > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Cloudflare Tunnel started
) else (
    echo [ERROR] Tunnel failed. Check: logs\cloudflared.log
)

:done
echo.
echo ============================================
echo   All services started!
echo ============================================
echo.
echo   Frontend:    http://localhost
echo   API docs:    http://localhost:8000/docs
echo   Qdrant:      http://localhost:6333/dashboard
echo   Tunnel:      https://chatflow-live.com
echo.
echo   Sandbox:     3 workers (ports 2222-2224)
echo   Workers:     8 Gunicorn (GUNICORN_WORKERS)
echo.
echo   Commands:
echo     Logs:      docker compose -f llm-chat\docker-compose.prod.yml logs -f backend
echo     Status:    docker compose -f llm-chat\docker-compose.prod.yml ps
echo     Stop:      stop.bat
echo ============================================
popd
pause
