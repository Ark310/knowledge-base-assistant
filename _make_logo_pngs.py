"""One-off: rasterize Contoso_Logo.svg (297.5x70) to PNGs for in-app
branding. Run once: scraper/venv/Scripts/python.exe _make_logo_pngs.py"""
import sys
from pathlib import Path
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).parent
SVG = ROOT / "Contoso_Logo.svg"
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)
AR = 297.5 / 70.0  # aspect ratio


def render(out: Path, height: int):
    r = QSvgRenderer(str(SVG))
    w = int(round(height * AR))
    img = QImage(w, height, QImage.Format_ARGB32)
    img.fill(0)  # transparent
    p = QPainter(img)
    r.render(p, QRectF(0, 0, w, height))
    p.end()
    img.save(str(out), "PNG")
    print(f"wrote {out} ({w}x{height})")


app = QApplication(sys.argv)  # QImage/QPainter need a QApplication
render(ASSETS / "contoso_logo.png", 36)      # header height
render(ASSETS / "contoso_logo_lg.png", 96)   # welcome/splash/About
