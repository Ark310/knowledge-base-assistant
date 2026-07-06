@echo off
REM One-folder v4.0.3 build into the MAIN dist/ folder (fresh workpath; OneDrive lock workaround).
scraper\venv\Scripts\python.exe -m PyInstaller ContosoKBScraper-v4.0.3.spec --noconfirm --workpath build_v403 --distpath dist
echo Build complete: dist\ContosoKBScraper-v4.0.3\ContosoKBScraper.exe
