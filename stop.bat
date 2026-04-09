@echo off
title ChatFlow - Stop All
chcp 65001 > nul
pushd "%~dp0"

echo ============================================
echo   ChatFlow Stop All Services
echo ============================================
echo.

set "COMPOSE_DIR=%~dp0llm-chat"
set "SANDBOX_DIR=%~dp0llm-chat\sandbox"

REM Stop Cloudflare Tunnel
echo [1/4] Stopping Cloudflare Tunnel...
taskkill /f /im cloudflared.exe > nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Tunnel stopped.
) else (
    echo [SKIP] Tunnel was not running.
)

REM Check Docker
docker info > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Docker is not running.
    pause
    exit /b 1
)

REM Stop main services
echo.
echo [2/4] Stopping main services...
cd /d "%COMPOSE_DIR%"
docker compose -f docker-compose.prod.yml down 2>nul
docker compose down 2>nul
echo [OK] Main services stopped.

REM Stop sandbox
echo.
echo [3/4] Stopping sandbox...
cd /d "%SANDBOX_DIR%"
docker compose --profile cluster down 2>nul
docker compose --profile standalone down 2>nul
echo [OK] Sandbox stopped.

REM Verify
echo.
echo [4/4] Done.
echo.
echo ============================================
echo   All services stopped.
echo ============================================
popd
pause
