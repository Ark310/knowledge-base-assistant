@echo off
setlocal
pushd "%~dp0"
echo Building ContosoKBChatbot.exe...
"scraper\venv\Scripts\python.exe" -m PyInstaller ContosoKBChatbot.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo.
echo Build complete. Artifact: dist\ContosoKBChatbot\ContosoKBChatbot.exe  (distribute the whole ContosoKBChatbot folder).
pause
popd
endlocal
