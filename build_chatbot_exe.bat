@echo off
setlocal
pushd "%~dp0"
echo Building ContosoKBChatbot.exe...
"scraper\venv\Scripts\python.exe" -m PyInstaller ContosoKBChatbot.spec --workpath build_v301 --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo.
echo Build complete. Artifact: dist\ContosoKBChatbot-v3.0.1\ContosoKBChatbot-v3.0.1.exe  (distribute the whole ContosoKBChatbot-v3.0.1 folder).
pause
popd
endlocal
