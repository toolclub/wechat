@echo off
title ChatFlow - Start
chcp 65001 > nul

echo ============================================
echo   ChatFlow Docker Compose Start
echo ============================================
echo.

set "ROOT_DIR=%~dp0"
set "COMPOSE_DIR=%~dp0llm-chat"
set "CLOUDFLARED=%~dp0cloudflared.exe"
set "CLOUDFLARED_CONFIG=%~dp0cloudflared-config.yml"

REM -- Check Docker is running --
docker info > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not running. Please start Docker Desktop first.
    pause
    exit /b 1
)

REM -- Create logs directory (mounted into container) --
if not exist "%~dp0logs" mkdir "%~dp0logs"

echo [1/3] Building and starting all services...
cd /d "%COMPOSE_DIR%"
docker compose up -d --build
if %errorlevel% neq 0 (
    echo [ERROR] docker compose up failed.
    pause
    exit /b 1
)

echo.
echo [2/3] Waiting for services to become healthy...
timeout /t 5 /nobreak > nul

REM -- Show container status --
docker compose ps
echo.

REM -- Start cloudflared tunnel as Windows Service (survives bat close + reboot) --
echo [3/3] Starting Cloudflare Tunnel...

if not exist "%CLOUDFLARED%" (
    echo [WARN] cloudflared.exe not found, skipping tunnel.
    goto :done
)

if not exist "%CLOUDFLARED_CONFIG%" (
    echo [WARN] cloudflared-config.yml not found, skipping tunnel.
    goto :done
)

REM -- Check if service already registered --
sc query cloudflared > nul 2>&1
if %errorlevel% neq 0 (
    echo      Registering cloudflared as Windows service...
    "%CLOUDFLARED%" --config "%CLOUDFLARED_CONFIG%" service install
    if %errorlevel% neq 0 (
        echo [ERROR] Failed to install cloudflared service. Try running as Administrator.
        goto :tunnel_fallback
    )
    echo      [OK] Service registered.
)

REM -- Start the service (ignore error if already running) --
net start cloudflared > nul 2>&1
timeout /t 3 /nobreak > nul

sc query cloudflared | findstr "RUNNING" > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Cloudflare Tunnel service is running.
    goto :done
) else (
    echo [WARN] Service did not start cleanly, falling back to foreground process...
    goto :tunnel_fallback
)

:tunnel_fallback
REM -- Fallback: run in a separate visible window so it survives bat close --
echo      Starting tunnel in separate window ^(keep it open^)...
taskkill /f /im cloudflared.exe > nul 2>&1
start "Cloudflare Tunnel" "%CLOUDFLARED%" tunnel --config "%CLOUDFLARED_CONFIG%" run
timeout /t 3 /nobreak > nul
tasklist | findstr /i "cloudflared" > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Cloudflare Tunnel started in separate window.
) else (
    echo [ERROR] Tunnel failed to start. Check logs\cloudflared.log for details.
)

:done
echo.
echo ============================================
echo   All services started!
echo ============================================
echo.
echo   Frontend:  http://localhost
echo   API docs:  http://localhost:8000/docs
echo   Qdrant:    http://localhost:6333/dashboard
echo   Tunnel:    https://chatflow-live.com
echo.
echo   Logs:
echo     App logs:   %~dp0logs\
echo     Container:  docker compose -f "%COMPOSE_DIR%\docker-compose.yml" logs -f backend
echo     Tunnel:     sc query cloudflared  ^(service mode^)
echo.
echo   To stop everything, run stop.bat
echo ============================================
pause