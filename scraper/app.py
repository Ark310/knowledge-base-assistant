# scraper/app.py
"""Entry point for the Contoso KB Scraper v4.
Applies the brand theme, shows an animated branded splash, then opens MainWindow.
Keep top-level imports light (PySide6 + config/theme only) so the splash paints
before any heavy engine import."""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Allow running as a script (`python scraper/app.py`): put the repo root on the
# path so `import scraper...` resolves. Harmless when frozen (PyInstaller manages path).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from scraper import theme
from scraper.config import APP_VERSION


def _make_splash() -> QSplashScreen | None:
    """Branded splash: Contoso logo on a white card with a brand-blue bottom bar.
    Returns None if the logo asset is absent — degrades gracefully."""
    lg = theme.asset_path("contoso_logo_lg.png")
    if not lg:
        # Fall back to a plain branded canvas when the logo is missing
        canvas = QPixmap(480, 260)
        canvas.fill(QColor(theme.PALETTE["surface"]))
        painter = QPainter(canvas)
        painter.setPen(QColor(theme.PALETTE["text"]))
        painter.setFont(QFont("Segoe UI", 14, QFont.Bold))
        painter.drawText(0, 0, canvas.width(), canvas.height() - 20,
                         Qt.AlignCenter, f"Contoso KB Scraper  v{APP_VERSION}")
        painter.fillRect(0, canvas.height() - 4, canvas.width(), 4,
                         QColor(theme.PALETTE["brand"]))
        painter.end()
        return QSplashScreen(canvas)

    logo = QPixmap(str(lg))
    if logo.isNull():
        return None
    logo = logo.scaledToWidth(340, Qt.SmoothTransformation)
    canvas = QPixmap(520, 300)
    canvas.fill(QColor(theme.PALETTE["surface"]))
    painter = QPainter(canvas)
    x = (canvas.width() - logo.width()) // 2
    y = (canvas.height() - logo.height()) // 2 - 18
    painter.drawPixmap(x, y, logo)
    painter.setPen(QColor(theme.PALETTE["muted"]))
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(0, y + logo.height() + 26, canvas.width(), 24,
                     Qt.AlignHCenter,
                     f"KB Scraper  ·  v{APP_VERSION}  ·  Starting…")
    painter.fillRect(0, canvas.height() - 4, canvas.width(), 4,
                     QColor(theme.PALETTE["brand"]))
    painter.end()
    return QSplashScreen(canvas)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(f"Contoso KB Scraper v{APP_VERSION}")
    app.setStyleSheet(theme.app_stylesheet())

    # Apply window/taskbar icon
    ico = theme.asset_path("scraper_icon.ico")
    if ico:
        app.setWindowIcon(QIcon(str(ico)))

    # Splash — paint before any heavy imports, with a brief fade-in (the startup animation)
    splash = _make_splash()
    if splash is not None:
        splash.setWindowOpacity(0.0)
        splash.show()
        for _step in range(1, 11):          # ~220ms fade-in
            splash.setWindowOpacity(_step / 10.0)
            app.processEvents()
            time.sleep(0.022)

    # Heavy import happens only after splash is visible
    from scraper.gui import MainWindow  # noqa: PLC0415
    win = MainWindow()
    win.show()
    if splash is not None:
        splash.finish(win)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
