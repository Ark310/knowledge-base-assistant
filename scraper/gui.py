"""V2.1 desktop GUI. Run from source: scraper\\venv\\Scripts\\python.exe scraper\\gui.py
Packaged as ContosoKBScraper.exe via PyInstaller."""
from __future__ import annotations
import sys
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtGui import QIcon, QPixmap, QTextCursor, QFont, QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QPlainTextEdit, QProgressBar, QFrame,
    QStatusBar, QMessageBox, QTabWidget,
)

from scraper.config import APP_VERSION, PRODUCTS, LOG_FILE
from scraper.engine import Engine, EngineCallbacks, CancellationToken
from scraper.kb_tab import KBTab
from scraper.ticket_tab import TicketTab
from scraper import theme

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)


class SignalBridge(QObject):
    log_sig      = Signal(str, str)
    status_sig   = Signal(str, dict)
    progress_sig = Signal(str, str, int, int)
    started_sig  = Signal(str)
    finished_sig = Signal(str, dict)


class BridgeCallbacks(EngineCallbacks):
    def __init__(self, bridge: SignalBridge):
        self.bridge = bridge
    def on_log(self, level, msg):                self.bridge.log_sig.emit(level, msg)
    def on_status(self, product, stats):         self.bridge.status_sig.emit(product, dict(stats))
    def on_progress(self, product, ver, i, n):   self.bridge.progress_sig.emit(product, ver, i, n)
    def on_started(self, action):                self.bridge.started_sig.emit(action)
    def on_finished(self, action, report):       self.bridge.finished_sig.emit(action, dict(report))


class Worker(QThread):
    def __init__(self, engine: Engine, action: str, kwargs: dict):
        super().__init__()
        self.engine = engine
        self.action = action
        self.kwargs = kwargs
    def run(self):
        try:
            method = getattr(self.engine, self.action)
            method(**self.kwargs)
        except Exception as exc:
            logging.exception("Worker action %s raised", self.action)
            self.engine.cb.on_log("error", f"Action {self.action} crashed: {exc}")


class StatusCard(QFrame):
    def __init__(self, product_key: str, display_name: str, on_scrape):
        super().__init__()
        self.product_key = product_key
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(220)
        v = QVBoxLayout(self)
        title = QLabel(f"<b>{display_name}</b>")
        title.setStyleSheet("font-size: 14px;")
        v.addWidget(title)
        self.lbl_discovered = QLabel("Discovered: —")
        self.lbl_new        = QLabel("New: 0")
        self.lbl_skipped    = QLabel("Skipped: 0")
        self.lbl_failed     = QLabel("Failed: 0")
        for w in (self.lbl_discovered, self.lbl_new, self.lbl_skipped, self.lbl_failed):
            v.addWidget(w)
        row = QHBoxLayout()
        self.btn_scrape = QPushButton("Scrape")
        self.chk_force  = QCheckBox("Force")
        self.btn_scrape.clicked.connect(lambda: on_scrape(self.product_key, self.chk_force.isChecked()))
        row.addWidget(self.btn_scrape); row.addWidget(self.chk_force); row.addStretch()
        v.addLayout(row)
        v.addStretch()

    def update_stats(self, stats: dict):
        self.lbl_discovered.setText(f"Discovered: {stats.get('discovered', '—')}")
        self.lbl_new.setText(f"New: {stats.get('new', 0)}")
        self.lbl_skipped.setText(f"Skipped: {stats.get('skipped', 0)}")
        self.lbl_failed.setText(f"Failed: {stats.get('failed', 0)}")

    def set_enabled(self, enabled: bool):
        self.btn_scrape.setEnabled(enabled)
        self.chk_force.setEnabled(enabled)


class MainWindow(QMainWindow):
    MAX_LOG_LINES = 5000

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Contoso KB Scraper v{APP_VERSION}")
        self.resize(1100, 740)

        # Window/taskbar icon
        ico = theme.asset_path("scraper_icon.ico")
        if ico:
            self.setWindowIcon(QIcon(str(ico)))

        self.bridge = SignalBridge()
        self.cancel_token = CancellationToken()
        self.engine = Engine(callbacks=BridgeCallbacks(self.bridge), cancel_token=self.cancel_token)
        self.worker: Worker | None = None

        self._build_ui()
        self._wire_signals()
        self._set_running(False)
        self._log("info", "Ready. Use the toolbar to validate, discover, or scrape.")

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

        self.tabs.addTab(self._build_v1_widget(), "v1 — Release Notes")
        self.kb_tab = KBTab()
        self.tabs.addTab(self.kb_tab, "v2 — Knowledge Base")
        self.ticket_tab = TicketTab()
        self.tabs.addTab(self.ticket_tab, "v3 — Ticket Portal")

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

    def _build_v1_widget(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)

        btn_row = QHBoxLayout()
        self.btn_validate = QPushButton("Validate")
        self.btn_discover = QPushButton("Discover / Refresh URLs")
        self.btn_indexes  = QPushButton("Rebuild Indexes")
        self.btn_stop     = QPushButton("⏹ STOP")
        for btn in (self.btn_validate, self.btn_discover, self.btn_indexes, self.btn_stop):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        cards_row = QHBoxLayout()
        self.cards: dict[str, StatusCard] = {}
        for key, cfg in PRODUCTS.items():
            card = StatusCard(key, cfg["display_name"], on_scrape=self._scrape_one)
            self.cards[key] = card
            cards_row.addWidget(card)
        outer.addLayout(cards_row)

        self.lbl_progress = QLabel("Idle")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        outer.addWidget(self.lbl_progress)
        outer.addWidget(self.progress)

        bulk = QHBoxLayout()
        self.btn_scrape_all = QPushButton("Scrape ALL (incremental)")
        self.btn_force_all  = QPushButton("Force re-scrape ALL")
        bulk.addWidget(self.btn_scrape_all)
        bulk.addWidget(self.btn_force_all)
        bulk.addStretch()
        outer.addLayout(bulk)

        outer.addWidget(QLabel("<b>Log</b>"))
        self.log_pane = QPlainTextEdit()
        self.log_pane.setReadOnly(True)
        self.log_pane.setMaximumBlockCount(self.MAX_LOG_LINES)
        self.log_pane.setFont(QFont("Consolas", 9))
        outer.addWidget(self.log_pane, stretch=1)

        return w

    def _wire_signals(self):
        self.bridge.log_sig.connect(self._log)
        self.bridge.status_sig.connect(self._on_status)
        self.bridge.progress_sig.connect(self._on_progress)

        self.btn_validate.clicked.connect(lambda: self._start("validate"))
        self.btn_discover.clicked.connect(lambda: self._start("discover_and_update_config"))
        self.btn_indexes.clicked.connect(lambda: self._start("rebuild_indexes"))
        self.btn_stop.clicked.connect(self._stop)
        self.btn_scrape_all.clicked.connect(lambda: self._start("scrape_all", {"force": False}))
        self.btn_force_all.clicked.connect(lambda: self._start("scrape_all", {"force": True}))

    def _start(self, action: str, kwargs: dict | None = None):
        if self.worker and self.worker.isRunning():
            self._log("warning", "A run is already in progress; ignoring request.")
            return
        self.cancel_token = CancellationToken()
        self.engine.cancel = self.cancel_token
        self.worker = Worker(self.engine, action, kwargs or {})
        self.worker.finished.connect(self._worker_done)
        self._set_running(True)
        self._log("info", f"--- Starting: {action} ---")
        self.worker.start()

    def _scrape_one(self, product_key: str, force: bool):
        self._start("scrape_product", {"product_key": product_key, "force": force})

    def _stop(self):
        if self.worker and self.worker.isRunning():
            self._log("warning", "Cancel requested — will stop after current page completes.")
            self.cancel_token.cancel()

    def _worker_done(self):
        self._set_running(False)
        self._log("info", "--- Run complete ---")
        self.lbl_progress.setText("Idle")
        self.progress.setValue(0)

    def _set_running(self, running: bool):
        for btn in (self.btn_validate, self.btn_discover, self.btn_indexes,
                    self.btn_scrape_all, self.btn_force_all):
            btn.setEnabled(not running)
        for card in self.cards.values():
            card.set_enabled(not running)
        self.btn_stop.setEnabled(running)

    @Slot(str, str)
    def _log(self, level: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"{ts} {level.upper():7s} {msg}"
        cursor = self.log_pane.textCursor()
        fmt = QTextCharFormat()
        if level == "error":     fmt.setForeground(QColor("#c62828"))
        elif level == "warning": fmt.setForeground(QColor("#ef6c00"))
        elif level == "info":    fmt.setForeground(QColor("#212121"))
        else:                    fmt.setForeground(QColor("#616161"))
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(line + "\n", fmt)
        self.log_pane.setTextCursor(cursor)
        self.log_pane.ensureCursorVisible()
        getattr(logging, level if level in ("debug","info","warning","error","critical") else "info")(msg)

    @Slot(str, dict)
    def _on_status(self, product: str, stats: dict):
        card = self.cards.get(product)
        if card:
            card.update_stats(stats)

    @Slot(str, str, int, int)
    def _on_progress(self, product: str, version: str, idx: int, total: int):
        self.lbl_progress.setText(f"Now scraping: {product} — {version}   ({idx} / {total})")
        pct = int(idx * 100 / total) if total else 0
        self.progress.setValue(pct)

    def closeEvent(self, event):
        # Drain ALL running workers (a child widget's own closeEvent does not fire when
        # the parent window closes). The ticket worker may be PAUSED — TicketTab.shutdown()
        # cancels (which releases the pause) and joins it, avoiding a QThread destroyed
        # while still running.
        v1_running = bool(self.worker and self.worker.isRunning())
        ticket_running = bool(getattr(self.ticket_tab, "_worker", None)
                              and self.ticket_tab._worker.isRunning())
        if v1_running or ticket_running:
            reply = QMessageBox.question(self, "Quit?",
                "A scrape is running. Stop it and quit?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                event.ignore(); return
            if v1_running:
                self.cancel_token.cancel()
                self.worker.wait(15_000)
            if ticket_running:
                self.ticket_tab.shutdown()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Contoso KB Scraper")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
