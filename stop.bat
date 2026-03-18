@echo off
title LLM Chat - Stop

echo ============================================
echo   Stop All LLM Chat Services
echo ============================================
echo.

REM -- Compute project path (no trailing backslash) for PowerShell matching --
set "PROJ_PATH=%~dp0"
set "PROJ_PATH=%PROJ_PATH:~0,-1%"

REM -- 1. Stop Cloudflare tunnel --
echo [1/4] Stopping Cloudflare tunnel...
taskkill /FI "WINDOWTITLE eq LLM-Cloudflared" /T /F > nul 2>&1
taskkill /IM cloudflared.exe /F > nul 2>&1
echo     Done.

REM -- 2. Stop frontend window --
echo [2/4] Stopping frontend...
taskkill /FI "WINDOWTITLE eq LLM-Frontend" /T /F > nul 2>&1
echo     Done.

REM -- 3. Stop backend window --
echo [3/4] Stopping backend...
taskkill /FI "WINDOWTITLE eq LLM-Backend" /T /F > nul 2>&1
echo     Done.

REM -- 4. Kill any remaining project processes by path --
echo [4/4] Cleaning up residual processes...

taskkill /IM cloudflared.exe /F > nul 2>&1

powershell -NoProfile -NonInteractive -Command "$p='%PROJ_PATH%'; Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and ($_.CommandLine -like ('*' + $p + '*') -or $_.ExecutablePath -like ('*' + $p + '*')) } | ForEach-Object { $_.Terminate() | Out-Null }" > nul 2>&1

powershell -NoProfile -NonInteractive -Command "$p='%PROJ_PATH%'; Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'node.exe' -and ($_.CommandLine -like ('*' + $p + '*') -or $_.ExecutablePath -like ('*' + $p + '*')) } | ForEach-Object { $_.Terminate() | Out-Null }" > nul 2>&1

timeout /t 2 /nobreak > nul

REM -- Verify clean --
echo.
echo Verifying...
set LEFTOVER=0

tasklist /FI "IMAGENAME eq cloudflared.exe" 2>nul | findstr "cloudflared.exe" >nul
if %errorlevel%==0 (
    echo [WARN] cloudflared.exe still running, force killing...
    taskkill /IM cloudflared.exe /F > nul 2>&1
    set LEFTOVER=1
)

powershell -NoProfile -NonInteractive -Command "$p='%PROJ_PATH%'; $r=Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and ($_.CommandLine -like ('*' + $p + '*') -or $_.ExecutablePath -like ('*' + $p + '*')) }; if($r){ $r | ForEach-Object { $_.Terminate() | Out-Null }; Write-Output 'found'}" 2>nul | findstr "found" >nul
if %errorlevel%==0 (
    echo [WARN] Python process needed second kill pass.
    set LEFTOVER=1
)

powershell -NoProfile -NonInteractive -Command "$p='%PROJ_PATH%'; $r=Get-WmiObject Win32_Process | Where-Object { $_.Name -eq 'node.exe' -and ($_.CommandLine -like ('*' + $p + '*') -or $_.ExecutablePath -like ('*' + $p + '*')) }; if($r){ $r | ForEach-Object { $_.Terminate() | Out-Null }; Write-Output 'found'}" 2>nul | findstr "found" >nul
if %errorlevel%==0 (
    echo [WARN] Node process needed second kill pass.
    set LEFTOVER=1
)

echo.
echo ============================================
if %LEFTOVER%==0 (
    echo   All services stopped cleanly.
) else (
    echo   All services stopped (with extra cleanup pass).
)
echo ============================================
pause
