@echo off
REM ============================================================
REM  MNN B-Roll Footage Search Engine - launcher
REM  Double-click this file to open the search window.
REM ============================================================
setlocal
cd /d "%~dp0"

REM Prefer the Windows Python launcher, fall back to python on PATH.
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% main.py
if %errorlevel% neq 0 (
    echo.
    echo The app exited with an error. If this is the first run, try
    echo double-clicking "Setup (first time).bat" to install requirements.
    echo.
    pause
)
endlocal
