# scraper/kb_tab.py
from __future__ import annotations
import logging
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QTextCursor, QFont, QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QPlainTextEdit, QProgressBar, QFrame, QScrollArea, QGroupBox,
)

from scraper.kb_config import KB_PRODUCT_GROUPS
from scraper.kb_engine import KBEngine
from scraper.engine import EngineCallbacks, CancellationToken


class _SignalBridge(QObject):
    log_sig      = Signal(str, str)
    status_sig   = Signal(str, dict)
    progress_sig = Signal(str, str, int, int)
    started_sig  = Signal(str)
    finished_sig = Signal(str, dict)


class _BridgeCallbacks(EngineCallbacks):
    def __init__(self, bridge: _SignalBridge):
        self.bridge = bridge
    def on_log(self, level, msg):                  self.bridge.log_sig.emit(level, msg)
    def on_status(self, key, stats):               self.bridge.status_sig.emit(key, dict(stats))
    def on_progress(self, key, title, i, n):       self.bridge.progress_sig.emit(key, title, i, n)
    def on_started(self, action):                  self.bridge.started_sig.emit(action)
    def on_finished(self, action, report):         self.bridge.finished_sig.emit(action, dict(report))


class _Worker(QThread):
    def __init__(self, engine: KBEngine, action: str, kwargs: dict):
        super().__init__()
        self.engine = engine
        self.action = action
        self.kwargs = kwargs

    def run(self):
        try:
            getattr(self.engine, self.action)(**self.kwargs)
        except Exception as exc:
            logging.exception("KBWorker %s raised", self.action)
            self.engine.cb.on_log("error", f"{self.action} crashed: {exc}")


class KBSpaceCard(QFrame):
    """Status card for one Confluence space — mirrors v1 StatusCard."""

    def __init__(self, space_key: str, display_name: str, on_scrape):
        super().__init__()
        self.space_key = space_key
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedWidth(160)
        self.setMinimumHeight(115)

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 4)
        v.setSpacing(2)

        lbl = QLabel(f"<b>{display_name}</b>")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size: 11px;")
        v.addWidget(lbl)

        self.lbl_found   = QLabel("Found: —")
        self.lbl_new     = QLabel("New: 0")
        self.lbl_skipped = QLabel("Skip: 0")
        self.lbl_failed  = QLabel("Fail: 0")
        for w in (self.lbl_found, self.lbl_new, self.lbl_skipped, self.lbl_failed):
            w.setStyleSheet("font-size: 10px;")
            v.addWidget(w)
        self.lbl_failed.setStyleSheet("font-size: 10px; color: #c62828;")

        row = QHBoxLayout()
        self.btn_scrape = QPushButton("Scrape")
        self.btn_scrape.setFixedHeight(22)
        self.chk_force = QCheckBox("F")
        self.chk_force.setToolTip("Force re-scrape")
        self.btn_scrape.clicked.connect(
            lambda: on_scrape(self.space_key, self.chk_force.isChecked())
        )
        row.addWidget(self.btn_scrape)
        row.addWidget(self.chk_force)
        v.addLayout(row)

    def update_stats(self, stats: dict):
        self.lbl_found.setText(f"Found: {stats.get('discovered', '—')}")
        self.lbl_new.setText(f"New: {stats.get('new', 0)}")
        self.lbl_skipped.setText(f"Skip: {stats.get('skipped', 0)}")
        self.lbl_failed.setText(f"Fail: {stats.get('failed', 0)}")

    def set_enabled(self, enabled: bool):
        self.btn_scrape.setEnabled(enabled)
        self.chk_force.setEnabled(enabled)


class KBTab(QWidget):
    """v2 Knowledge Base scraper tab — self-contained, no shared state with v1."""

    MAX_LOG_LINES = 5000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = _SignalBridge()
        self.cancel_token = CancellationToken()
        self.engine = KBEngine(
            callbacks=_BridgeCallbacks(self.bridge),
            cancel_token=self.cancel_token,
        )
        self.worker: _Worker | None = None
        self.cards: dict[str, KBSpaceCard] = {}
        self._build_ui()
        self._wire_signals()
        self._set_running(False)
        self._log("info", "v2 Knowledge Base Scraper ready.")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        # Top action buttons
        btn_row = QHBoxLayout()
        self.btn_validate = QPushButton("Validate")
        self.btn_indexes  = QPushButton("Rebuild Indexes")
        self.btn_stop     = QPushButton("⏹ STOP")
        for btn in (self.btn_validate, self.btn_indexes, self.btn_stop):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        # Scrollable space cards grouped by product family
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(300)
        container = QWidget()
        cards_layout = QVBoxLayout(container)
        cards_layout.setSpacing(8)

        for group_label, spaces in KB_PRODUCT_GROUPS.items():
            box = QGroupBox(group_label)
            row = QHBoxLayout(box)
            row.setSpacing(6)
            for cfg in spaces:
                card = KBSpaceCard(cfg["space_key"], cfg["display_name"], self._scrape_one)
                self.cards[cfg["space_key"]] = card
                row.addWidget(card)
            row.addStretch()
            cards_layout.addWidget(box)

        scroll.setWidget(container)
        outer.addWidget(scroll)

        # Progress bar
        self.lbl_progress = QLabel("Idle")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        outer.addWidget(self.lbl_progress)
        outer.addWidget(self.progress)

        # Bulk scrape buttons
        bulk = QHBoxLayout()
        self.btn_scrape_all = QPushButton("Scrape ALL (incremental)")
        self.btn_force_all  = QPushButton("Force re-scrape ALL")
        bulk.addWidget(self.btn_scrape_all)
        bulk.addWidget(self.btn_force_all)
        bulk.addStretch()
        outer.addLayout(bulk)

        # Log pane
        outer.addWidget(QLabel("<b>Log</b>"))
        self.log_pane = QPlainTextEdit()
        self.log_pane.setReadOnly(True)
        self.log_pane.setMaximumBlockCount(self.MAX_LOG_LINES)
        self.log_pane.setFont(QFont("Consolas", 9))
        outer.addWidget(self.log_pane, stretch=1)

    def _wire_signals(self):
        self.bridge.log_sig.connect(self._log)
        self.bridge.status_sig.connect(self._on_status)
        self.bridge.progress_sig.connect(self._on_progress)
        self.btn_validate.clicked.connect(lambda: self._start("validate"))
        self.btn_indexes.clicked.connect(lambda: self._start("rebuild_indexes"))
        self.btn_stop.clicked.connect(self._stop)
        self.btn_scrape_all.clicked.connect(lambda: self._start("scrape_all", {"force": False}))
        self.btn_force_all.clicked.connect(lambda: self._start("scrape_all", {"force": True}))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _start(self, action: str, kwargs: dict | None = None):
        if self.worker and self.worker.isRunning():
            self._log("warning", "A KB run is already in progress.")
            return
        self.cancel_token = CancellationToken()
        self.engine.cancel = self.cancel_token
        self.worker = _Worker(self.engine, action, kwargs or {})
        self.worker.finished.connect(self._worker_done)
        self._set_running(True)
        self._log("info", f"--- Starting: {action} ---")
        self.worker.start()

    def _scrape_one(self, space_key: str, force: bool):
        self._start("scrape_space", {"space_key": space_key, "force": force})

    def _stop(self):
        if self.worker and self.worker.isRunning():
            self._log("warning", "Cancel requested — stopping after current article.")
            self.cancel_token.cancel()

    def _worker_done(self):
        self._set_running(False)
        self._log("info", "--- Run complete ---")
        self.lbl_progress.setText("Idle")
        self.progress.setValue(0)

    def _set_running(self, running: bool):
        for btn in (self.btn_validate, self.btn_indexes, self.btn_scrape_all, self.btn_force_all):
            btn.setEnabled(not running)
        for card in self.cards.values():
            card.set_enabled(not running)
        self.btn_stop.setEnabled(running)

    # ── Slots ─────────────────────────────────────────────────────────────────

    @Slot(str, str)
    def _log(self, level: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"{ts} {level.upper():7s} {msg}"
        cursor = self.log_pane.textCursor()
        fmt = QTextCharFormat()
        if level == "error":     fmt.setForeground(QColor("#c62828"))
        elif level == "warning": fmt.setForeground(QColor("#ef6c00"))
        else:                    fmt.setForeground(QColor("#212121"))
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(line + "\n", fmt)
        self.log_pane.setTextCursor(cursor)
        self.log_pane.ensureCursorVisible()
        getattr(logging, level if level in ("debug", "info", "warning", "error", "critical") else "info")(msg)

    @Slot(str, dict)
    def _on_status(self, space_key: str, stats: dict):
        card = self.cards.get(space_key)
        if card:
            card.update_stats(stats)

    @Slot(str, str, int, int)
    def _on_progress(self, space_key: str, title: str, idx: int, total: int):
        self.lbl_progress.setText(f"Scraping: {space_key} — {title}  ({idx}/{total})")
        self.progress.setValue(int(idx * 100 / total) if total else 0)
