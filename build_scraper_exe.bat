@echo off
REM One-folder v4 build into fresh work/dist paths (OneDrive --clean lock workaround).
scraper\venv\Scripts\python.exe -m PyInstaller ContosoKBScraper-v4.spec --noconfirm --workpath build_v4 --distpath dist-v4
echo Build complete: dist-v4\ContosoKBScraper-v4\ContosoKBScraper.exe
