@echo off
setlocal
pushd "%~dp0"
REM Output goes to the MAIN checkout's dist\ (three levels up from this worktree).
REM Stable ContosoKBChatbot.exe is never touched: different output name, and
REM PyInstaller --clean only clears its own build cache, not dist contents.
set DIST_DIR=%~dp0..\..\..\dist
echo Building ContosoKBChatbot-BETA.exe into %DIST_DIR% ...
"%~dp0..\..\..\scraper\venv\Scripts\python.exe" -m PyInstaller ContosoKBChatbot-BETA.spec --distpath "%DIST_DIR%" --workpath build_beta --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] Beta build failed.
    pause
    exit /b 1
)
echo.
echo Build complete. Artifact: %DIST_DIR%\ContosoKBChatbot-BETA.exe
pause
popd
endlocal
