@echo off
setlocal EnableDelayedExpansion
title Xoraclips - Setup and Launcher

:: Ensure we run from the directory containing this script
cd /d "%~dp0"

echo.
echo  ======================================================================
echo                       XORACLIPS - WINDOWS LAUNCHER                
echo  ======================================================================
echo.

:: -------------------------------------------------------------------------
:: Jump to main execution flow
:: -------------------------------------------------------------------------
goto :main

:: -------------------------------------------------------------------------
:: Subroutine: Refresh PATH from Windows Registry (Machine + User)
:: -------------------------------------------------------------------------
:refresh_path
for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do call set "SYS_PATH=%%B"
for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do call set "USER_PATH=%%B"
set "PATH=%USER_PATH%;%SYS_PATH%;%LOCALAPPDATA%\Microsoft\WinGet\Links;%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts;%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;C:\Program Files\Git\cmd;C:\Program Files\nodejs;%PATH%"
exit /b 0

:main
:: Check for winget availability
where winget >nul 2>&1
if %errorlevel% equ 0 (
    set "HAS_WINGET=1"
) else (
    set "HAS_WINGET=0"
    echo [NOTE] Windows Package Manager winget not found.
    echo        If any tools are missing, please install them manually.
    echo.
)

:: -------------------------------------------------------------------------
:: STEP 1: Verify and Install Prerequisites
:: -------------------------------------------------------------------------
echo [STEP 1/4] Checking prerequisites...

:: 1. Git
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Git is NOT installed.
    if "!HAS_WINGET!"=="1" (
        echo [INFO] Installing Git via winget...
        winget install --id Git.Git -e --source winget --accept-source-agreements --accept-package-agreements
        call :refresh_path
    ) else (
        echo [ERROR] Git is required. Download and install from: https://git-scm.com/
        pause
        exit /b 1
    )
) else (
    echo [OK] Git is installed.
)

:: 2. Node.js
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Node.js is NOT installed.
    if "!HAS_WINGET!"=="1" (
        echo [INFO] Installing Node.js LTS via winget...
        winget install --id OpenJS.NodeJS.LTS -e --source winget --accept-source-agreements --accept-package-agreements
        call :refresh_path
    ) else (
        echo [ERROR] Node.js is required. Download and install from: https://nodejs.org/
        pause
        exit /b 1
    )
) else (
    echo [OK] Node.js is installed.
)

:: 3. Python 3.10+
set "PYTHON_CMD="
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYTHON_CMD=python"
) else (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if %errorlevel% equ 0 (
        set "PYTHON_CMD=py -3"
    )
)

if "%PYTHON_CMD%"=="" (
    echo [!] Python 3.10+ is NOT installed or not on PATH.
    if "!HAS_WINGET!"=="1" (
        echo [INFO] Installing Python 3.11 via winget...
        winget install --id Python.Python.3.11 -e --source winget --accept-source-agreements --accept-package-agreements
        call :refresh_path
        python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PYTHON_CMD=python"
        ) else (
            py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
            if !errorlevel! equ 0 (
                set "PYTHON_CMD=py -3"
            ) else (
                if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
                    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
                )
            )
        )
    ) else (
        echo [ERROR] Python 3.10+ is required. Download from: https://www.python.org/downloads/
        echo         Make sure to check "Add Python to PATH" during installation.
        pause
        exit /b 1
    )
)

if "%PYTHON_CMD%"=="" (
    echo [ERROR] Could not detect a working Python 3.10+ installation.
    pause
    exit /b 1
) else (
    echo [OK] Python is installed: !PYTHON_CMD!
)

:: 4. FFmpeg
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] FFmpeg is NOT installed.
    if "!HAS_WINGET!"=="1" (
        echo [INFO] Installing FFmpeg via winget...
        winget install --id Gyan.FFmpeg -e --source winget --accept-source-agreements --accept-package-agreements
        call :refresh_path
    ) else (
        echo [WARNING] FFmpeg is missing. Video rendering might fail without it.
    )
) else (
    echo [OK] FFmpeg is installed.
)

:: 5. yt-dlp
where yt-dlp >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] yt-dlp binary is NOT on system PATH.
    if "!HAS_WINGET!"=="1" (
        echo [INFO] Installing yt-dlp via winget...
        winget install --id yt-dlp.yt-dlp -e --source winget --accept-source-agreements --accept-package-agreements
        call :refresh_path
    )
) else (
    echo [OK] yt-dlp is installed.
)

:: Refresh PATH one more time to pick up all changes
call :refresh_path

:: -------------------------------------------------------------------------
:: STEP 2: Clone Repository or skip if already present
:: -------------------------------------------------------------------------
echo.
echo [STEP 2/4] Checking repository location...

if exist "package.json" (
    if exist "backend\main.py" (
        echo [OK] Already inside Xoraclips directory. Skipping clone.
        goto :in_repo
    )
)

if exist "xoraclips\package.json" (
    echo [OK] Existing xoraclips folder found. Skipping clone.
    cd "xoraclips"
    goto :in_repo
)

echo [INFO] Cloning Xoraclips repository from GitHub...
git clone https://github.com/M1xora/xoraclips.git
if !errorlevel! neq 0 (
    echo [ERROR] Git clone failed. Please check your internet connection.
    pause
    exit /b 1
)

cd "xoraclips"
if !errorlevel! neq 0 (
    echo [ERROR] Failed to access xoraclips directory.
    pause
    exit /b 1
)

:in_repo

:: Handle optional --update argument
if "%1"=="--update" (
    echo [INFO] Updating repository via git pull...
    git pull
    if exist "venv\.installed" del "venv\.installed"
)

:: -------------------------------------------------------------------------
:: STEP 3: Install Dependencies
:: -------------------------------------------------------------------------
echo.
echo [STEP 3/4] Checking and installing project dependencies...

:: Create empty environment configs if missing
if not exist ".env" (
    echo # XORACLIPS root environment config > .env
)
if not exist "backend\.env" (
    echo # XORACLIPS backend environment config > backend\.env
)

:: A. Frontend Dependencies
if not exist "node_modules" (
    echo [INFO] Installing Node.js packages via npm install...
    call npm install
    if !errorlevel! neq 0 (
        echo [ERROR] npm install failed.
        pause
        exit /b 1
    )
    echo [OK] Frontend dependencies installed.
) else (
    echo [OK] Frontend packages already installed - node_modules found.
)

:: B. Backend Dependencies in Virtual Environment
if not exist "venv\Scripts\activate.bat" (
    echo [INFO] Creating Python virtual environment venv...
    !PYTHON_CMD! -m venv venv
    if !errorlevel! neq 0 (
        python -m venv venv
    )
)

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Could not create Python virtual environment.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

:: venv\.installed holds a copy of the requirements it installed: when
:: backend\requirements.txt changes, existing installs get the new packages too (#76).
set "NEED_DEPS=0"
if not exist "venv\.installed" set "NEED_DEPS=1"
if exist "venv\.installed" fc /b "backend\requirements.txt" "venv\.installed" >nul 2>&1 || set "NEED_DEPS=1"

if "!NEED_DEPS!"=="1" (
    echo [INFO] Installing Python dependencies from backend\requirements.txt...
    echo [INFO] Note: First time installation may take a few minutes.
    python -m pip install --upgrade pip --quiet
    pip install -r backend\requirements.txt
    if !errorlevel! neq 0 (
        echo [ERROR] Failed to install backend dependencies.
        pause
        exit /b 1
    )
    python -m pip install --upgrade "yt-dlp[default]" --quiet
    if !errorlevel! neq 0 (
        echo [WARN] Could not upgrade yt-dlp - keeping the version from requirements.txt.
    )
    copy /y "backend\requirements.txt" "venv\.installed" >nul
    echo [OK] Backend dependencies installed successfully.
) else (
    echo [OK] Backend dependencies already installed - venv ready.
)

:: -------------------------------------------------------------------------
:: STEP 4: Launch the App
:: start-xoraclips.bat starts the backend and the new UI (port 5174) in
:: their own windows, skips what is already running, and opens the browser
:: once both are ready. The current folder is the repository here (it may be
:: a fresh clone), so the file is called by its full path in this folder.
:: -------------------------------------------------------------------------
echo.
echo [STEP 4/4] Starting Xoraclips...
call "%CD%\start-xoraclips.bat"
exit /b %errorlevel%
