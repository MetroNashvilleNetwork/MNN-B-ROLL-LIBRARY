@echo off
REM ============================================================
REM  MNN Auto-Editor - worker.
REM  Called by the Windows scheduled task AND by
REM  "Make Videos Now.bat". Reads the settings + Gemini key saved
REM  during Setup, then renders a vertical + landscape cut into a
REM  timestamped folder under output\.
REM  (Don't double-click this directly - use "Make Videos Now.bat".)
REM ============================================================
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 ( set "PY=py -3" ) else ( set "PY=python" )

if not exist "_autoedit_settings.bat" (
    echo Settings not found. Run "Setup Auto-Editor (first time).bat" first.
    exit /b 1
)
call "_autoedit_settings.bat"

REM Load the Gemini key if present (turns on the AI director). Without it the
REM editor automatically falls back to its offline quality-based selection.
set "DIRECTOR="
if exist ".gemini_key" (
    set /p GEMINI_API_KEY=<".gemini_key"
    set "DIRECTOR=--director"
)

REM Timestamp so runs don't overwrite each other.
for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set "STAMP=%%I"

%PY% -m broll_search.editor %DIRECTOR% ^
  --clips "%FOOTAGE%" --music "%MUSIC%" ^
  --out "%OUTPUT%\%STAMP%-%THEME%" ^
  --theme "%THEME%" --duration %DURATION% --profile %PROFILE%

exit /b %errorlevel%
