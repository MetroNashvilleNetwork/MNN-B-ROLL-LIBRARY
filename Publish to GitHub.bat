@echo off
REM ============================================================
REM  Publish MNN B-Roll Library to GitHub
REM  One-time: creates the GitHub link you can send your team.
REM ============================================================
setlocal
cd /d "%~dp0"

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo Git is not installed. Install Git for Windows from https://git-scm.com/download/win
    echo then run this again.
    pause
    exit /b 1
)

echo ============================================================
echo  STEP 1 - Create an empty repo on GitHub (in your browser):
echo.
echo    1. Go to:  https://github.com/new
echo    2. Repository name:  MNN-B-Roll-Library
echo    3. Choose  Public
echo    4. Do NOT check "Add a README" (leave everything unchecked)
echo    5. Click  Create repository
echo    6. Copy the URL it shows, e.g.
echo         https://github.com/YOURNAME/MNN-B-Roll-Library.git
echo ============================================================
echo.
set /p REPOURL=STEP 2 - Paste that repository URL here and press Enter:
if "%REPOURL%"=="" ( echo No URL entered. & pause & exit /b 1 )

git remote remove origin >nul 2>nul
git remote add origin %REPOURL%
git branch -M main

echo.
echo Pushing your code to GitHub...
echo (A browser window may open for you to sign in to GitHub - that's normal.)
echo.
git push -u origin main
if %errorlevel% neq 0 (
    echo.
    echo Push failed - see the messages above. If it asked for a password,
    echo GitHub now needs a "Personal Access Token" instead; ask IT, or use
    echo the GitHub Desktop app to publish this folder.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  DONE!  Your code is now on GitHub.
echo  Send your team this link:
echo     %REPOURL:.git=%
echo ============================================================
pause
endlocal
