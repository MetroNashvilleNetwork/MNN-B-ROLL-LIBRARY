@echo off
REM ============================================================
REM  MNN B-Roll Library - SHARE ON NETWORK
REM  Use this to let someone else (e.g. your manager) open the
REM  library from THEIR computer on the same MNN network.
REM  A link will be shown in this window - send it to them.
REM  Keep this window open while they view; close it to stop.
REM ============================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 ( set "PY=py -3" ) else ( set "PY=python" )

%PY% main.py --share
if %errorlevel% neq 0 (
    echo.
    echo The app exited with an error. If this is the first run, try
    echo "Setup (first time).bat" first.
    echo.
    pause
)
endlocal
