@echo off
REM One-folder v4.0.4 build into the MAIN dist/ folder (fresh workpath; OneDrive lock workaround).
scraper\venv\Scripts\python.exe -m PyInstaller ContosoKBScraper-v4.0.4.spec --noconfirm --workpath build_v404 --distpath dist
echo Build complete: dist\ContosoKBScraper-v4.0.4\ContosoKBScraper.exe
