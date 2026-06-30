# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("playwright", "PySide6"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

datas += [("assets", "assets")]   # logos + ice-scraper icon (theme.asset_path reads sys._MEIPASS/assets when frozen)
hiddenimports += [
    "bs4", "lxml", "lxml._elementpath",
    "keyring", "keyring.backends", "keyring.backends.Windows",
    "keyring.backends.fail", "keyring.credentials",
]

a = Analysis(
    ["scraper/app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[], runtime_hooks=[],
    excludes=[
        # QtWidgets-only app — drop the heavy Qt modules we never import
        # (QtWebEngine alone is ~150 MB; we scrape via Playwright's browser).
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DExtras", "PySide6.Qt3DAnimation",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,           # one-folder: binaries go in COLLECT, not the exe
    name="ContosoKBScraper",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False,
    icon="assets/scraper_icon.ico",
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="ContosoKBScraper-v4.0.1",
)
