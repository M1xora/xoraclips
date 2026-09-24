@echo off
:: Delayed expansion stays off until the folder is entered: with it on, a
:: "!" in the folder name would be dropped from the path.
setlocal
title Xoraclips - Start

:: Work from the folder this file is in, even from a desktop shortcut or
:: another folder. Everything below uses paths relative to it, so folder
:: names with spaces, "(" or "!" are fine ("&" is refused below).
cd /d "%~dp0" || (
    echo [X] Folder Xoraclips tidak bisa dibuka.
    pause
    exit /b 1
)
setlocal EnableDelayedExpansion

set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5174"
set "APP_URL=http://localhost:%FRONTEND_PORT%/preview.html"
rem The API description is answered locally; /api/health can wait on Supadata.
set "API_URL=http://127.0.0.1:%BACKEND_PORT%/openapi.json"
set "XC_LOCK=%TEMP%\xoraclips-start.lock"
set "RC=0"

echo.
echo  ==============================================================
echo                    XORACLIPS - MENYALAKAN
echo  ==============================================================
echo.

:: --- 0. Only one start at a time (a double-click on the shortcut) ---------
mkdir "%XC_LOCK%" 2>nul
if errorlevel 1 (
    call :lock_is_stale
    if "!STALE!"=="1" (
        rd "%XC_LOCK%" 2>nul
        mkdir "%XC_LOCK%" 2>nul
    ) else (
        echo [X] Start Xoraclips sedang berjalan di jendela lain. Tunggu sebentar.
        ping -n 4 127.0.0.1 >nul
        exit /b 1
    )
)

:: --- 1. Everything installed? ------------------------------------------
rem npm's own helper files break on a folder path with "&"; say so now
rem instead of waiting 90 seconds for a frontend that cannot start.
echo "%CD%"| findstr /c:"&" >nul && (
    echo [X] Nama folder mengandung tanda "&". npm tidak bisa berjalan di folder seperti itu.
    echo     Ganti nama foldernya tanpa "&", lalu coba lagi.
    goto :fail
)
if not exist "venv\Scripts\python.exe" (
    echo [X] Python venv belum ada. Jalankan setup_and_run.bat sekali dulu.
    goto :fail
)
if not exist "node_modules" (
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
call :port_pid %BACKEND_PORT%
if defined PORT_PID (
    call :backend_ours
    if "!OURS!"=="1" (
        echo [OK] Backend sudah menyala di port %BACKEND_PORT%. Tidak dijalankan lagi.
    ) else (
        echo [X] Port %BACKEND_PORT% dipakai program lain, bukan backend Xoraclips. PID !PORT_PID!.
        echo     Tutup program itu dulu, lalu coba lagi.
        goto :fail
    )
) else (
    echo [..] Menyalakan backend di jendela "Xoraclips Backend"...
    rem XORACLIPS_ROLE marks the window, so stop-xoraclips.bat can find it.
    start "Xoraclips Backend" cmd /k "set XORACLIPS_ROLE=backend&& venv\Scripts\python.exe -m uvicorn backend.main:app --port %BACKEND_PORT%"
)

:: --- 3. Frontend: same checks ---------------------------------------------
call :port_pid %FRONTEND_PORT%
if defined PORT_PID (
    call :frontend_ours
    if "!OURS!"=="1" (
        echo [OK] Frontend sudah menyala di port %FRONTEND_PORT%. Tidak dijalankan lagi.
    ) else (
        echo [X] Port %FRONTEND_PORT% dipakai program lain, bukan frontend Xoraclips. PID !PORT_PID!.
        echo     Tutup program itu dulu, lalu coba lagi.
        goto :fail
    )
) else (
    echo [..] Menyalakan frontend di jendela "Xoraclips Frontend"...
    rem --no-open: the browser is opened below, once both are ready.
    rem --strictPort: fail instead of silently moving to another port.
    start "Xoraclips Frontend" cmd /k "set XORACLIPS_ROLE=frontend&& npm run dev-next -- --no-open --strictPort"
)

:: --- 4. Wait until both answer: 90 seconds by the clock --------------------
echo [..] Menunggu backend dan frontend siap...
call :now
set /a DEADLINE=NOW+90
:wait_loop
call :backend_ours
set "BACK_OK=!OURS!"
call :frontend_ours
set "FRONT_OK=!OURS!"
if "!BACK_OK!!FRONT_OK!"=="11" goto :ready
call :now
if !NOW! geq !DEADLINE! goto :too_slow
rem About one second; ping also works when there is no keyboard input.
ping -n 2 127.0.0.1 >nul
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
goto :finish

:too_slow
echo [X] Setelah 90 detik belum siap.
if "!BACK_OK!"=="0" echo     - Backend belum menjawab. Lihat pesan di jendela "Xoraclips Backend".
if "!FRONT_OK!"=="0" echo     - Frontend belum menjawab. Lihat pesan di jendela "Xoraclips Frontend".
goto :fail

:fail
set "RC=1"
echo.
pause

:finish
rd "%XC_LOCK%" 2>nul
exit /b %RC%

:: ---------------------------------------------------------------------------
:: :port_pid PORT  ->  PORT_PID = the program listening on PORT, or empty.
:: Asks Windows directly, so it works whatever the Windows language is.
:port_pid
set "PORT_PID="
for /f "usebackq delims=" %%p in (`powershell -NoProfile -Command "(Get-NetTCPConnection -State Listen -LocalPort %~1 -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess"`) do set "PORT_PID=%%p"
exit /b 0

:: :backend_ours  ->  OURS=1 if the backend answers as Xoraclips.
:backend_ours
set "OURS=0"
curl -s -m 5 --noproxy "*" "%API_URL%" 2>nul | findstr /c:"XORACLIPS API" >nul && set "OURS=1"
exit /b 0

:: :frontend_ours  ->  OURS=1 if the frontend serves the Xoraclips page.
:frontend_ours
set "OURS=0"
curl -s -m 5 --noproxy "*" "%APP_URL%" 2>nul | findstr /i /c:"Xoraclips" >nul && set "OURS=1"
exit /b 0

:: :now  ->  NOW = seconds since 1970, for the 90-second limit.
:now
for /f %%t in ('powershell -NoProfile -Command "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()"') do set "NOW=%%t"
exit /b 0

:: :lock_is_stale  ->  STALE=1 if the lock is older than 2 minutes (a start
:: that was closed halfway), so it does not block every later start.
:lock_is_stale
set "STALE=0"
powershell -NoProfile -Command "exit [int](((Get-Date) - (Get-Item $env:XC_LOCK).CreationTime).TotalSeconds -lt 120)" && set "STALE=1"
exit /b 0
