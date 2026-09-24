@echo off
setlocal EnableDelayedExpansion
title Xoraclips - Start

:: Work from the folder this file is in, even when opened from a desktop
:: shortcut or from another folder. ROOT ends with a backslash.
cd /d "%~dp0"
set "ROOT=%~dp0"

set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5174"
set "APP_URL=http://localhost:%FRONTEND_PORT%/preview.html"
set "HEALTH_URL=http://127.0.0.1:%BACKEND_PORT%/api/health"

echo.
echo  ==============================================================
echo                    XORACLIPS - MENYALAKAN
echo  ==============================================================
echo.

:: --- 1. Everything installed? ------------------------------------------
if not exist "%ROOT%venv\Scripts\python.exe" (
    echo [X] Python venv belum ada. Jalankan setup_and_run.bat sekali dulu.
    goto :fail
)
if not exist "%ROOT%node_modules" (
    echo [X] Paket frontend belum terpasang. Jalankan setup_and_run.bat sekali dulu.
    goto :fail
)
where npm >nul 2>&1 || (
    echo [X] npm tidak ditemukan. Pasang Node.js dulu, atau jalankan setup_and_run.bat.
    goto :fail
)
where curl >nul 2>&1 || (
    echo [X] curl tidak ditemukan. Perlu Windows 10 versi 1803 atau lebih baru.
    goto :fail
)

:: --- 2. Backend: already ours, busy with something else, or free? ---------
call :port_busy %BACKEND_PORT%
if "!PORT_BUSY!"=="1" (
    call :backend_ours
    if "!OURS!"=="1" (
        echo [OK] Backend sudah menyala di port %BACKEND_PORT%. Tidak dijalankan lagi.
    ) else (
        echo [X] Port %BACKEND_PORT% dipakai program lain, bukan backend Xoraclips.
        echo     Tutup program itu dulu, lalu coba lagi.
        goto :fail
    )
) else (
    echo [..] Menyalakan backend di jendela "Xoraclips Backend"...
    start "Xoraclips Backend" /D "%ROOT%" cmd /k ""%ROOT%venv\Scripts\python.exe" -m uvicorn backend.main:app --port %BACKEND_PORT%"
)

:: --- 3. Frontend: same checks ---------------------------------------------
call :port_busy %FRONTEND_PORT%
if "!PORT_BUSY!"=="1" (
    call :frontend_ours
    if "!OURS!"=="1" (
        echo [OK] Frontend sudah menyala di port %FRONTEND_PORT%. Tidak dijalankan lagi.
    ) else (
        echo [X] Port %FRONTEND_PORT% dipakai program lain, bukan frontend Xoraclips.
        echo     Tutup program itu dulu, lalu coba lagi.
        goto :fail
    )
) else (
    echo [..] Menyalakan frontend di jendela "Xoraclips Frontend"...
    rem --no-open: the browser is opened below, once both are ready.
    rem --strictPort: fail instead of silently moving to another port.
    start "Xoraclips Frontend" /D "%ROOT%" cmd /k "npm run dev-next -- --no-open --strictPort"
)

:: --- 4. Wait until both answer (up to 90 seconds) -------------------------
echo [..] Menunggu backend dan frontend siap...
set /a WAITED=0
:wait_loop
call :backend_ours
set "BACK_OK=!OURS!"
call :frontend_ours
set "FRONT_OK=!OURS!"
if "!BACK_OK!!FRONT_OK!"=="11" goto :ready
if !WAITED! geq 90 goto :too_slow
rem About one second; ping also works when there is no keyboard input.
ping -n 2 127.0.0.1 >nul
set /a WAITED+=1
goto :wait_loop

:ready
echo [OK] Xoraclips siap: %APP_URL%
if defined XORACLIPS_NO_BROWSER (
    echo      Browser tidak dibuka karena XORACLIPS_NO_BROWSER diset.
) else (
    start "" "%APP_URL%"
)
echo.
echo  Untuk mematikan: jalankan stop-xoraclips.bat
echo.
exit /b 0

:too_slow
echo [X] Setelah 90 detik belum siap.
if "!BACK_OK!"=="0" echo     - Backend belum menjawab. Lihat pesan di jendela "Xoraclips Backend".
if "!FRONT_OK!"=="0" echo     - Frontend belum menjawab. Lihat pesan di jendela "Xoraclips Frontend".
goto :fail

:fail
echo.
pause
exit /b 1

:: ---------------------------------------------------------------------------
:: :port_busy PORT  ->  PORT_BUSY=1 if a program is listening on that port.
:: Only LISTENING lines whose local address ends in exactly ":PORT".
:port_busy
set "PORT_BUSY=0"
for /f "tokens=2" %%a in ('netstat -ano ^| findstr /c:"LISTENING"') do (
    echo %%a| findstr /e /c:":%~1" >nul && set "PORT_BUSY=1"
)
exit /b 0

:: :backend_ours  ->  OURS=1 if the backend answers as Xoraclips.
:backend_ours
set "OURS=0"
curl -s -m 3 "%HEALTH_URL%" 2>nul | findstr /i /c:"XORACLIPS" >nul && set "OURS=1"
exit /b 0

:: :frontend_ours  ->  OURS=1 if the frontend serves the Xoraclips page.
:frontend_ours
set "OURS=0"
curl -s -m 3 "%APP_URL%" 2>nul | findstr /i /c:"Xoraclips" >nul && set "OURS=1"
exit /b 0
