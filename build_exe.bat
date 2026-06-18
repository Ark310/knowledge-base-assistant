@echo off
setlocal
pushd "%~dp0"
echo Building ContosoKBScraper.exe...
"scraper\venv\Scripts\python.exe" -m PyInstaller ContosoKBScraper.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo.
echo Build complete. Artifact: dist\ContosoKBScraper.exe
pause
popd
endlocal
