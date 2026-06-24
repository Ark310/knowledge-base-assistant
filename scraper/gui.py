"""V4 desktop GUI — two tabs: Tickets + Knowledge Base.
Run from source: scraper\\venv\\Scripts\\python.exe scraper\\gui.py
Packaged as ContosoKBScraper.exe via PyInstaller."""
from __future__ import annotations
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame,
    QStatusBar, QMessageBox, QTabWidget,
)

from scraper.config import APP_VERSION, LOG_FILE
from scraper.kb_tab import KBTab
from scraper.ticket_tab import TicketTab
from scraper import theme

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Contoso KB Scraper v{APP_VERSION}")
        self.resize(1100, 740)

        # Window/taskbar icon
        ico = theme.asset_path("scraper_icon.ico")
        if ico:
            self.setWindowIcon(QIcon(str(ico)))

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)

        # Brand header — installed as the QMainWindow menu-widget so it renders
        # above the toolbar dock area (the very top of the window chrome).
        self.setMenuWidget(self._build_header())

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)

        self.ticket_tab = TicketTab()
        self.tabs.addTab(self.ticket_tab, "Tickets")

        self.kb_tab = KBTab()
        self.tabs.addTab(self.kb_tab, "Knowledge Base")

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(f"Log file: {LOG_FILE}")

    def _build_header(self) -> QWidget:
        """Top brand bar: logo + 'Contoso KB Scraper' title + version pill + ⚙ Settings."""
        P = theme.PALETTE
        header = QFrame()
        header.setObjectName("HeaderBar")
        header.setStyleSheet(
            f"#HeaderBar {{ background:{P['surface']}; "
            f"border-bottom:2px solid {P['brand']}; }}")
        row = QHBoxLayout(header)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(10)

        # Logo (optional — degrade gracefully if missing)
        logo_lbl = QLabel()
        lp = theme.asset_path("contoso_logo.png")
        if lp:
            pm = QPixmap(str(lp))
            if not pm.isNull():
                logo_lbl.setPixmap(pm.scaledToHeight(26, Qt.SmoothTransformation))
        row.addWidget(logo_lbl)

        title = QLabel("Contoso KB Scraper")
        title.setStyleSheet(
            f"font-size:12pt; font-weight:600; color:{P['text']};")
        row.addWidget(title)
        row.addStretch()

        ver = QLabel(f"v{APP_VERSION}")
        ver.setStyleSheet(
            f"color:{P['surface']}; background:{P['brand']}; "
            f"border-radius:8px; padding:2px 8px; font-size:8.5pt;")
        row.addWidget(ver)

        self.btn_settings = QPushButton("⚙  Settings")
        self.btn_settings.setToolTip("Configure output folders and portal credentials")
        self.btn_settings.clicked.connect(self._open_settings)
        row.addWidget(self.btn_settings)

        return header

    def _open_settings(self):
        from scraper.settings_dialog import SettingsDialog
        SettingsDialog(self).exec()

    def closeEvent(self, event):
        # Drain BOTH tabs — each tab's shutdown() cancels (which releases any pause)
        # and joins its worker, avoiding a QThread destroyed while still running.
        ticket_running = (hasattr(self, "ticket_tab")
                          and getattr(self.ticket_tab, "_worker", None) is not None
                          and self.ticket_tab._worker.isRunning())
        kb_running = (hasattr(self, "kb_tab")
                      and getattr(self.kb_tab, "worker", None) is not None
                      and self.kb_tab.worker.isRunning())
        if ticket_running or kb_running:
            reply = QMessageBox.question(self, "Quit?",
                "A scrape is running. Stop it and quit?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        if hasattr(self, "ticket_tab"):
            self.ticket_tab.shutdown()
        if hasattr(self, "kb_tab"):
            self.kb_tab.shutdown()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Contoso KB Scraper")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
