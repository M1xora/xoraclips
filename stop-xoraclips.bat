@echo off
setlocal EnableDelayedExpansion
title Xoraclips - Stop

:: Work from the folder this file is in (also from a desktop shortcut).
cd /d "%~dp0"

echo.
echo  ==============================================================
echo                    XORACLIPS - MEMATIKAN
echo  ==============================================================
echo.

:: 1. Close the windows start-xoraclips.bat opened, with what runs in them.
::    They are found by the exact command they run, not by window title
::    (Windows Terminal hides console titles from taskkill).
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe'\" | Where-Object { $_.CommandLine -like '*uvicorn backend.main:app*' -or $_.CommandLine -like '*dev-next -- --no-open --strictPort*' } | ForEach-Object { taskkill /PID $_.ProcessId /T /F | Out-Null; '[OK] Jendela Xoraclips ditutup (PID ' + $_.ProcessId + ').' }"

:: 2. Whatever still listens on the two ports (for example started by hand)
::    is stopped too. Other node.exe or python.exe programs are left alone.
call :stop_port 8000 Backend
call :stop_port 5174 Frontend

echo.
echo  Selesai.
ping -n 3 127.0.0.1 >nul
exit /b 0

:: ---------------------------------------------------------------------------
:: :stop_port PORT NAME  ->  stops whatever listens on PORT, with its children.
:stop_port
set "STOPPED=0"
for /f "tokens=2,5" %%a in ('netstat -ano ^| findstr /c:"LISTENING"') do (
    echo %%a| findstr /e /c:":%~1" >nul && (
        rem PID 0 and 4 are Windows itself: never touch them.
        if not "%%b"=="0" if not "%%b"=="4" (
            taskkill /PID %%b /T /F >nul 2>&1 && set "STOPPED=1"
        )
    )
)
if "!STOPPED!"=="1" (
    echo [OK] %~2 di port %~1 dimatikan.
) else (
    echo [OK] Port %~1 untuk %~2 sudah bebas.
)
exit /b 0
