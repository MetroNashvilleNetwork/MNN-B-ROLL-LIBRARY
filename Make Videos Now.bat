@echo off
REM ============================================================
REM  MNN Auto-Editor - make videos now (manual run).
REM  Produces a vertical (9:16) + landscape (16:9) cut into a new
REM  folder under output\. Safe to run anytime.
REM ============================================================
setlocal
cd /d "%~dp0"
echo Making videos - this can take several minutes on a large library...
echo (The first run also analyzes your footage; later runs are faster.)
echo.
call "_run_auto_editor.bat"
if %errorlevel% neq 0 (
    echo.
    echo The run hit a problem. If this is the first time, run
    echo "Setup Auto-Editor (first time).bat" first.
    pause & exit /b %errorlevel%
)
echo.
echo Done! Your videos are in the output\ folder - open the newest folder.
echo Each run gives you a vertical.mp4 and a landscape.mp4.
pause
endlocal
