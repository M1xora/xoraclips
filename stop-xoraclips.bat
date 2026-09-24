@echo off
:: Delayed expansion stays off until the folder is entered (see start).
setlocal
title Xoraclips - Stop
cd /d "%~dp0" || exit /b 1
setlocal EnableDelayedExpansion

set "API_URL=http://127.0.0.1:8000/openapi.json"
set "APP_URL=http://localhost:5174/preview.html"

echo.
echo  ==============================================================
echo                    XORACLIPS - MEMATIKAN
echo  ==============================================================
echo.

:: 1. Close the windows start-xoraclips.bat opened, with what runs in them.
::    They carry XORACLIPS_ROLE in their command; window titles are not
::    used because Windows Terminal hides them from taskkill.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Where-Object { $_.CommandLine -like '*XORACLIPS_ROLE=backend*' -or $_.CommandLine -like '*XORACLIPS_ROLE=frontend*' } | ForEach-Object { taskkill /PID $_.ProcessId /T /F | Out-Null; '[OK] Jendela Xoraclips ditutup. PID ' + $_.ProcessId }"

:: 2. A Xoraclips still listening on its port (for example started by hand)
::    is stopped too. Anything else on these ports is left alone, and so are
::    all other node.exe and python.exe programs.
call :stop_port 8000 Backend backend_ours
call :stop_port 5174 Frontend frontend_ours

echo.
echo  Selesai.
ping -n 3 127.0.0.1 >nul
exit /b 0

:: ---------------------------------------------------------------------------
:: :stop_port PORT NAME CHECK  ->  stops what listens on PORT if CHECK says
:: it is Xoraclips.
:stop_port
call :port_pid %~1
if not defined PORT_PID (
    echo [OK] Port %~1 untuk %~2 sudah bebas.
    exit /b 0
)
call :%~3
if "!OURS!"=="1" (
    taskkill /PID !PORT_PID! /T /F >nul 2>&1
    echo [OK] %~2 Xoraclips di port %~1 dimatikan.
) else (
    echo [--] Port %~1 dipakai program lain, bukan Xoraclips. PID !PORT_PID!, tidak dimatikan.
)
exit /b 0

:port_pid
set "PORT_PID="
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "(Get-NetTCPConnection -State Listen -LocalPort %~1 -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"`) do set "PORT_PID=%%p"
exit /b 0

:backend_ours
set "OURS=0"
curl -s -m 5 --noproxy "*" "%API_URL%" 2>nul | findstr /c:"XORACLIPS API" >nul && set "OURS=1"
exit /b 0

:frontend_ours
set "OURS=0"
curl -s -m 5 --noproxy "*" "%APP_URL%" 2>nul | findstr /i /c:"Xoraclips" >nul && set "OURS=1"
exit /b 0
