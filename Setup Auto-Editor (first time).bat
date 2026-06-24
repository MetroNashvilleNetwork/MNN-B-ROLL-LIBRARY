@echo off
REM ============================================================
REM  MNN Auto-Editor - first-time setup (run ONCE on the server).
REM  Installs the editor's Python packages, checks for ffmpeg,
REM  asks for your footage folder + music folder + Gemini key,
REM  and (optionally) schedules the automatic twice-weekly run.
REM  Requires Python 3.9+ with "Add to PATH" checked.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 ( set "PY=py -3" ) else ( set "PY=python" )

echo Checking Python...
%PY% --version
if %errorlevel% neq 0 (
    echo.
    echo Python was not found. Install Python 3 from https://www.python.org/downloads/
    echo and check "Add Python to PATH" during install, then run this again.
    pause & exit /b 1
)

echo.
echo Installing packages ^(this can take several minutes^)...
%PY% -m pip install --upgrade pip
%PY% -m pip install -r requirements.txt
%PY% -m pip install -r requirements-editor.txt
if %errorlevel% neq 0 (
    echo.
    echo Package install failed. Check the internet connection and try again.
    pause & exit /b 1
)

echo.
echo Checking ffmpeg...
where ffmpeg >nul 2>nul
if %errorlevel% neq 0 (
    if not exist "tools\ffmpeg.exe" (
        echo   WARNING: ffmpeg/ffprobe not found on PATH or in tools\.
        echo   The editor needs them. Download a FULL build from
        echo   https://www.gyan.dev/ffmpeg/builds/ ^(ffmpeg-release-full^) and put
        echo   ffmpeg.exe + ffprobe.exe into the tools\ folder, then re-run setup.
    ) else ( echo   Found bundled ffmpeg in tools\. )
) else ( echo   Found ffmpeg on PATH. )

echo.
echo === Tell the editor where your footage and music live ===
set /p FOOTAGE=Footage folder (e.g. X:\2026 Metro Nashville Archive B-Roll Footage):
set /p MUSIC=Music folder (a folder of tracks you have the rights to use):
set /p PROFILE=Camera profile - sony_slog3 / dji_dlogm / rec709 [sony_slog3]:
if "!PROFILE!"=="" set "PROFILE=sony_slog3"
set /p THEME=Theme label for the videos, or "auto" for AI [auto]:
if "!THEME!"=="" set "THEME=auto"

> "_autoedit_settings.bat" (
    echo @echo off
    echo set "FOOTAGE=!FOOTAGE!"
    echo set "MUSIC=!MUSIC!"
    echo set "OUTPUT=%~dp0output"
    echo set "THEME=!THEME!"
    echo set "PROFILE=!PROFILE!"
    echo set "DURATION=35"
)
echo   Saved your settings.

echo.
echo === Gemini API key (turns on the AI director) ===
echo Paste your key, or leave blank to use the offline quality-based editor.
echo It is stored locally in .gemini_key and is never committed or shared.
set /p GKEY=Gemini API key:
if not "!GKEY!"=="" (
    <nul set /p="!GKEY!" > ".gemini_key"
    echo   Saved your key.
)

echo.
choice /m "Schedule the automatic run twice a week (Mondays + Thursdays, 6am)"
if !errorlevel!==1 (
    schtasks /create /tn "MNN Auto-Editor" /tr "\"%~dp0_run_auto_editor.bat\"" /sc WEEKLY /d MON,THU /st 06:00 /f
    echo   Scheduled. Finished videos will appear in the output\ folder.
)

echo.
echo Setup complete. Use "Make Videos Now.bat" to run it on demand,
echo or wait for the scheduled run. Outputs land in the output\ folder.
pause
endlocal
