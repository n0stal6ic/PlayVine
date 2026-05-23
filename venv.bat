@echo off
title PlayVine
if not exist ".venv\Scripts\activate.bat" (
    echo  No Virtual Environment.
    echo  Run install.bat first.
	echo.
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
echo  PlayVine environment active.
echo  (type 'deactivate' to exit)
echo.
cmd /k