@echo off
REM One-folder v4.0.1 build into the MAIN dist/ folder (fresh workpath; OneDrive lock workaround).
scraper\venv\Scripts\python.exe -m PyInstaller ContosoKBScraper-v4.0.1.spec --noconfirm --workpath build_v401 --distpath dist
echo Build complete: dist\ContosoKBScraper-v4.0.1\ContosoKBScraper.exe
