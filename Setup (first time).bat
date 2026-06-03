@echo off
REM ============================================================
REM  MNN B-Roll Footage Search Engine - first-time setup
REM  Installs the Python packages the app needs (PyQt5).
REM  Run this once per computer. Requires Python 3.8+ installed.
REM ============================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

echo Checking for Python...
%PY% --version
if %errorlevel% neq 0 (
    echo.
    echo Python was not found. Install Python 3 from https://www.python.org/downloads/
    echo and be sure to check "Add Python to PATH" during install, then run this again.
    echo.
    pause
    exit /b 1
)

echo.
echo Installing required packages...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo Setup failed while installing packages. Check your internet connection
    echo and try again.
    echo.
    pause
    exit /b 1
)

echo.
echo Setup complete. You can now double-click "Run B-Roll Search.bat".
echo.
echo Optional: to show video durations, see tools\README.txt for ffprobe.
echo.
pause
endlocal
