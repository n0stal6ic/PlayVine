@echo off
title PlayVine Installer
setlocal enabledelayedexpansion
echo  PlayVine Installer
echo.
goto check
:check
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  Python not found.
    echo  Install Python 3.10, 3.11, or 3.12
    echo.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK] Python %PY_VER%

uv --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  uv not found. Installing via pip...
    pip install uv --quiet
    if %errorlevel% neq 0 (
        echo  Failed to install uv. 
		echo  Try manually: pip install uv
        pause
        exit /b 1
    )
)
for /f "tokens=2 delims= " %%v in ('uv --version 2^>^&1') do set UV_VER=%%v
echo  [OK] uv %UV_VER%
echo.
goto venv

:venv
echo  Creating virtual environment...
uv venv .venv
if %errorlevel% neq 0 (
    echo  Failed to create virtual environment.
    pause
    exit /b 1
)

echo  Installing dependencies...
uv sync
if %errorlevel% neq 0 (
    echo  uv sync failed. Check the error.
    pause
    exit /b 1
)
echo  Dependencies installed
echo.
goto binaries

:binaries
echo  Checking for required binaries...
echo.

set MISSING_REQUIRED=0
set MISSING_OPTIONAL=0
call :check_bin ffmpeg      required
call :check_bin ffprobe     required
call :check_bin mkvmerge    required
call :check_bin packager    optional
call :check_bin mp4decrypt  optional
call :check_bin N_m3u8DL-RE optional
call :check_bin aria2c      optional

echo.
if %MISSING_REQUIRED%==1 (
    echo  One or more required binaries are missing.
    echo  Place them in the binaries folder or add to PATH.
)
if %MISSING_OPTIONAL%==1 (
    echo  Some optional binaries are missing.
)
goto :after_binary_check

:check_bin
    set BIN=%1
    set KIND=%2
    set FOUND=0
    if exist "binaries\%BIN%.exe"  set FOUND=1
    if exist "binaries\%BIN%"      set FOUND=1
    where %BIN% >nul 2>&1 && set FOUND=1

    if !FOUND!==1 (
        echo    %BIN%
    ) else (
        if "%KIND%"=="required" (
            echo  [MISS] %BIN%  ^<-- required
            set MISSING_REQUIRED=1
        ) else (
            echo  [    ] %BIN%  ^(optional^)
            set MISSING_OPTIONAL=1
        )
    )
    exit /b
:after_binary_check
cls
echo.
echo   Installation complete!
echo.
echo  NEXT STEPS
echo.
echo  1. Activate the virtual environment
echo       venv.bat
echo.
echo  2. Place your CDM device file in:
echo       playvine\devices\
echo.
echo  3. Set your CDM in the config:
echo       playvine\playvine.yml
echo         cdm:
echo           default: 'your_device_filename'
echo.
echo  4. Add credentials or cookies:
echo       Credentials  ^(in playvine\playvine.yml^):
echo         credentials:
echo           MyService: 'username:password'
echo.
echo       Cookies  ^(Netscape Format^):
echo         playvine\Cookies\MyService\default.txt
echo.
echo  5. Add service scripts into:
echo       services\MyService.py
echo     Then register in  playvine\services\__init__.py:
echo       from services.MyService import MyService
echo       SERVICE_MAP["MyService"] = ["MSV", "myservice"]
echo.
echo  6. Add binaries into:
echo       binaries\
echo     or ensure they are on your system PATH.
echo.
echo  7. Test the setup:
echo       pv --help
echo       pv dl MyService TITLE_ID --list
echo       pv dl MyService TITLE_ID --dry-run -q 1080
echo       pv dl MyService TITLE_ID --keys
echo.
echo  Run pv dl --help for help.
echo.
pause