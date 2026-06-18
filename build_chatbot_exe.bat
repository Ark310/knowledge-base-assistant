@echo off
setlocal
pushd "%~dp0"
echo Building ContosoKBChatbot.exe...
"scraper\venv\Scripts\python.exe" -m PyInstaller ContosoKBChatbot.spec --workpath build_v291 --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo.
echo Build complete. Artifact: dist\ContosoKBChatbot-v2.9.1\ContosoKBChatbot-v2.9.1.exe  (distribute the whole ContosoKBChatbot-v2.9.1 folder).
pause
popd
endlocal
