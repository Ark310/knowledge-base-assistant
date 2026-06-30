@echo off
REM One-folder v4.0.2 build into the MAIN dist/ folder (fresh workpath; OneDrive lock workaround).
scraper\venv\Scripts\python.exe -m PyInstaller ContosoKBScraper-v4.0.2.spec --noconfirm --workpath build_v402 --distpath dist
echo Build complete: dist\ContosoKBScraper-v4.0.2\ContosoKBScraper.exe
