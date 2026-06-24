# scraper/kb_tab.py — Option C: families sidebar + per-family detail table
from __future__ import annotations
import logging
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtGui import QTextCursor, QFont, QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit, QProgressBar, QListWidget, QTableWidget,
    QTableWidgetItem, QSplitter, QLineEdit, QHeaderView,
)

import scraper.config as config
from scraper.kb_config import KB_PRODUCT_GROUPS
from scraper.kb_engine import KBEngine
from scraper.engine import Engine, EngineCallbacks, CancellationToken
from scraper.control import RunControl
import scraper.app_settings as app_settings


# ── Signal bridge (unchanged pattern) ────────────────────────────────────────

class _SignalBridge(QObject):
    log_sig      = Signal(str, str)
    status_sig   = Signal(str, dict)
    progress_sig = Signal(str, str, int, int)
    started_sig  = Signal(str)
    finished_sig = Signal(str, dict)


class _BridgeCallbacks(EngineCallbacks):
    def __init__(self, bridge: _SignalBridge):
        self.bridge = bridge
    def on_log(self, level, msg):            self.bridge.log_sig.emit(level, msg)
    def on_status(self, key, stats):         self.bridge.status_sig.emit(key, dict(stats))
    def on_progress(self, key, title, i, n): self.bridge.progress_sig.emit(key, title, i, n)
    def on_started(self, action):            self.bridge.started_sig.emit(action)
    def on_finished(self, action, report):   self.bridge.finished_sig.emit(action, dict(report))


# ── Worker — dispatches by engine instance + action name ─────────────────────

class _Worker(QThread):
    def __init__(self, engine, action: str, kwargs: dict, control: RunControl):
        super().__init__()
        self.engine  = engine
        self.action  = action
        self.kwargs  = kwargs
        self.control = control

    def run(self):
        try:
            getattr(self.engine, self.action)(**self.kwargs)
        except Exception as exc:
            logging.exception("KBWorker %s raised", self.action)
            self.engine.cb.on_log("error", f"{self.action} crashed: {exc}")


# ── Helpers ───────────────────────────────────────────────────────────────────

_DETAIL_COLS = ["Space", "Found", "New", "Skip", "Fail", ""]
_COL_FOUND, _COL_NEW, _COL_SKIP, _COL_FAIL, _COL_BTN = 1, 2, 3, 4, 5


def _make_family_map() -> dict[str, list[dict]]:
    """Return {label: [{key, display_name, engine_kind}]} for rail items."""
    families: dict[str, list[dict]] = {}
    for label, spaces in KB_PRODUCT_GROUPS.items():
        families[label] = [
            {"key": s["space_key"], "display_name": s["display_name"], "engine_kind": "kb"}
            for s in spaces
        ]
    families["Release Notes"] = [
        {"key": k, "display_name": v["display_name"], "engine_kind": "rn"}
        for k, v in config.PRODUCTS.items()
    ]
    return families


# ── KBTab ─────────────────────────────────────────────────────────────────────

class KBTab(QWidget):
    """Option C — families rail + per-family detail table.

    Two engines share a single RunControl:
      • KBEngine  for the 7 KB families
      • v1 Engine for Release Notes
    """

    MAX_LOG_LINES = 5000

    def __init__(self, parent=None):
        super().__init__(parent)

        # Shared pause/cancel token
        self._control: RunControl = RunControl()

        # Bridge + callbacks (one set, shared across both engines)
        self._bridge = _SignalBridge()
        self._cb = _BridgeCallbacks(self._bridge)

        # Engines — constructed once, wired to the same callbacks + control
        self._kb_engine = KBEngine(
            callbacks=self._cb,
            cancel_token=self._control,
            output_base=app_settings.kb_dir(),
        )
        self._rn_engine = Engine(
            callbacks=self._cb,
            cancel_token=self._control,
        )

        self.worker: _Worker | None = None

        # Family map: label -> [{key, display_name, engine_kind}]
        self._families: dict[str, list[dict]] = _make_family_map()

        # key -> detail row index (repopulated on each family selection)
        self._key_to_row: dict[str, int] = {}

        self._build_ui()
        self._wire_signals()
        self._set_running(False)
        self._log("info", "KB Scraper ready — select a family to begin.")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        # ── Top action row ────────────────────────────────────────────────────
        top = QHBoxLayout()
        self.btn_validate   = QPushButton("Validate")
        self.btn_rebuild    = QPushButton("Rebuild Indexes")
        self.btn_scrape_all = QPushButton("Scrape All")
        self.btn_scrape_all.setObjectName("PrimaryButton")
        self.btn_force_all  = QPushButton("Force All")
        self.btn_pause      = QPushButton("Pause")
        self.btn_stop       = QPushButton("Stop")
        self.inp_filter     = QLineEdit()
        self.inp_filter.setPlaceholderText("Filter spaces…")
        self.inp_filter.setMaximumWidth(180)
        for w in (self.btn_validate, self.btn_rebuild, self.btn_scrape_all,
                  self.btn_force_all, self.btn_pause, self.btn_stop):
            top.addWidget(w)
        top.addStretch()
        top.addWidget(self.inp_filter)
        outer.addLayout(top)

        # ── Master/detail split ───────────────────────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left rail — family list
        self.rail = QListWidget()
        self.rail.setMaximumWidth(200)
        self.rail.setMinimumWidth(140)
        for label in list(KB_PRODUCT_GROUPS.keys()) + ["Release Notes"]:
            self.rail.addItem(label)
        splitter.addWidget(self.rail)

        # Right detail — space table
        right = QWidget()
        right_v = QVBoxLayout(right)
        right_v.setContentsMargins(0, 0, 0, 0)
        right_v.setSpacing(4)

        # Family action header row (populated when a family is selected)
        self._fam_hdr = QHBoxLayout()
        self._lbl_fam = QLabel("")
        self._btn_scrape_fam = QPushButton("Scrape family")
        self._btn_force_fam  = QPushButton("Force family")
        self._fam_hdr.addWidget(self._lbl_fam)
        self._fam_hdr.addStretch()
        self._fam_hdr.addWidget(self._btn_scrape_fam)
        self._fam_hdr.addWidget(self._btn_force_fam)
        right_v.addLayout(self._fam_hdr)

        self.detail = QTableWidget(0, len(_DETAIL_COLS))
        self.detail.setHorizontalHeaderLabels(_DETAIL_COLS)
        self.detail.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.detail.horizontalHeader().setSectionResizeMode(_COL_BTN, QHeaderView.ResizeToContents)
        self.detail.setEditTriggers(QTableWidget.NoEditTriggers)
        self.detail.setSelectionBehavior(QTableWidget.SelectRows)
        self.detail.verticalHeader().setVisible(False)
        right_v.addWidget(self.detail, stretch=1)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, stretch=3)

        # ── Progress bar ──────────────────────────────────────────────────────
        self._lbl_progress = QLabel("Idle")
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        outer.addWidget(self._lbl_progress)
        outer.addWidget(self._progress)

        # ── Log pane ──────────────────────────────────────────────────────────
        outer.addWidget(QLabel("<b>Log</b>"))
        self.log_pane = QPlainTextEdit()
        self.log_pane.setReadOnly(True)
        self.log_pane.setMaximumBlockCount(self.MAX_LOG_LINES)
        self.log_pane.setFont(QFont("Consolas", 9))
        outer.addWidget(self.log_pane, stretch=1)

    def _wire_signals(self):
        self._bridge.log_sig.connect(self._log)
        self._bridge.status_sig.connect(self._on_status)
        self._bridge.progress_sig.connect(self._on_progress)

        self.rail.currentTextChanged.connect(self._populate_detail)

        self.btn_validate.clicked.connect(lambda: self._start_kb("validate"))
        self.btn_rebuild.clicked.connect(lambda: self._start_kb("rebuild_indexes"))
        self.btn_scrape_all.clicked.connect(self._scrape_all_action)
        self.btn_force_all.clicked.connect(self._force_all_action)
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_stop.clicked.connect(self._stop)
        self._btn_scrape_fam.clicked.connect(lambda: self._scrape_family(force=False))
        self._btn_force_fam.clicked.connect(lambda: self._scrape_family(force=True))
        self.inp_filter.textChanged.connect(self._filter_detail)

    # ── Family/detail population ──────────────────────────────────────────────

    def _populate_detail(self, family_label: str):
        """Repopulate the detail table with the spaces for family_label."""
        if not family_label:
            return
        spaces = self._families.get(family_label, [])
        self._lbl_fam.setText(f"<b>{family_label}</b>")
        self._current_family = family_label

        self.detail.setRowCount(0)
        self._key_to_row.clear()

        filter_text = self.inp_filter.text().lower()
        running = bool(self.worker and self.worker.isRunning())

        for row_idx, sp in enumerate(spaces):
            display = sp["display_name"]
            if filter_text and filter_text not in display.lower():
                continue
            actual_row = self.detail.rowCount()
            self.detail.insertRow(actual_row)
            self._key_to_row[sp["key"]] = actual_row

            self.detail.setItem(actual_row, 0, QTableWidgetItem(display))
            for col in (_COL_FOUND, _COL_NEW, _COL_SKIP, _COL_FAIL):
                self.detail.setItem(actual_row, col, QTableWidgetItem("—"))

            btn = QPushButton("Scrape")
            btn.setEnabled(not running)
            # capture loop vars
            key = sp["key"]
            kind = sp["engine_kind"]
            btn.clicked.connect(lambda _=False, k=key, kd=kind: self._scrape_space(k, kd, force=False))
            self.detail.setCellWidget(actual_row, _COL_BTN, btn)

    def _filter_detail(self, text: str):
        """Show/hide rows whose Space column matches the filter text."""
        text = text.lower()
        for row in range(self.detail.rowCount()):
            item = self.detail.item(row, 0)
            visible = (not text) or (item and text in item.text().lower())
            self.detail.setRowHidden(row, not visible)

    # ── Engine dispatch ───────────────────────────────────────────────────────

    def _fresh_control(self):
        """Reset the shared RunControl (used at start of each top-level action)."""
        self._control = RunControl()
        self._kb_engine.cancel = self._control
        self._rn_engine.cancel = self._control

    def _start_kb(self, action: str, kwargs: dict | None = None):
        """Dispatch a KBEngine action."""
        if self.worker and self.worker.isRunning():
            self._log("warning", "A run is already in progress.")
            return
        self._fresh_control()
        self.worker = _Worker(self._kb_engine, action, kwargs or {}, self._control)
        self.worker.finished.connect(self._worker_done)
        self._set_running(True)
        self._log("info", f"--- Starting: {action} ---")
        self.worker.start()

    def _start_rn(self, action: str, kwargs: dict | None = None):
        """Dispatch a v1 RN Engine action."""
        if self.worker and self.worker.isRunning():
            self._log("warning", "A run is already in progress.")
            return
        self._fresh_control()
        self.worker = _Worker(self._rn_engine, action, kwargs or {}, self._control)
        self.worker.finished.connect(self._worker_done)
        self._set_running(True)
        self._log("info", f"--- Starting RN: {action} ---")
        self.worker.start()

    def _scrape_space(self, key: str, engine_kind: str, force: bool):
        if engine_kind == "kb":
            self._start_kb("scrape_space", {"space_key": key, "force": force})
        else:
            self._start_rn("scrape_product", {"product_key": key, "force": force})

    def _scrape_family(self, force: bool):
        """Scrape all spaces in the currently selected family."""
        label = getattr(self, "_current_family", None)
        if not label:
            return
        spaces = self._families.get(label, [])
        if not spaces:
            return
        # All spaces in a KB family use KBEngine; RN family uses v1 Engine
        if spaces[0]["engine_kind"] == "kb":
            # Scrape each space sequentially via scrape_all for the family's keys
            self._start_kb("scrape_all", {"force": force})
        else:
            self._start_rn("scrape_all", {"force": force})

    def _scrape_all_action(self):
        """Scrape KB scrape_all then RN scrape_all (chained via two workers)."""
        if self.worker and self.worker.isRunning():
            self._log("warning", "A run is already in progress.")
            return
        self._log("info", "--- Scrape All: KB + Release Notes ---")
        self._fresh_control()
        self._pending_rn_after_kb = True
        self.worker = _Worker(self._kb_engine, "scrape_all", {"force": False}, self._control)
        self.worker.finished.connect(self._kb_done_start_rn)
        self._set_running(True)
        self.worker.start()

    def _force_all_action(self):
        """Force-scrape KB + RN (chained)."""
        if self.worker and self.worker.isRunning():
            self._log("warning", "A run is already in progress.")
            return
        self._log("info", "--- Force All: KB + Release Notes ---")
        self._fresh_control()
        self._pending_rn_after_kb = True
        self.worker = _Worker(self._kb_engine, "scrape_all", {"force": True}, self._control)
        self.worker.finished.connect(lambda: self._kb_done_start_rn(force=True))
        self._set_running(True)
        self.worker.start()

    @Slot()
    def _kb_done_start_rn(self, force: bool = False):
        """Called when KB scrape_all finishes; starts RN scrape_all next."""
        if self._control.is_cancelled():
            self._worker_done()
            return
        self._log("info", "--- KB done — starting Release Notes ---")
        self.worker = _Worker(self._rn_engine, "scrape_all", {"force": force}, self._control)
        self.worker.finished.connect(self._worker_done)
        self.worker.start()

    # ── Pause / Stop ──────────────────────────────────────────────────────────

    def _toggle_pause(self):
        if self._control.paused:
            self._control.resume()
            self.btn_pause.setText("Pause")
            self._log("info", "Resumed.")
        else:
            self._control.pause()
            self.btn_pause.setText("Resume")
            self._log("info", "Paused — will stop after current article.")

    def _stop(self):
        if self.worker and self.worker.isRunning():
            self._log("warning", "Stop requested — finishing current article then halting.")
            self._control.cancel()

    def shutdown(self):
        """Cancel any in-flight worker and wait for it to finish."""
        self._control.cancel()
        if self.worker and self.worker.isRunning():
            self.worker.wait(5000)

    # ── Worker lifecycle ──────────────────────────────────────────────────────

    @Slot()
    def _worker_done(self):
        self._set_running(False)
        self._log("info", "--- Run complete ---")
        self._lbl_progress.setText("Idle")
        self._progress.setValue(0)
        self.btn_pause.setText("Pause")

    def _set_running(self, running: bool):
        for btn in (self.btn_validate, self.btn_rebuild, self.btn_scrape_all,
                    self.btn_force_all, self._btn_scrape_fam, self._btn_force_fam):
            btn.setEnabled(not running)
        self.btn_pause.setEnabled(running)
        self.btn_stop.setEnabled(running)
        # per-space scrape buttons in the detail table
        for row in range(self.detail.rowCount()):
            w = self.detail.cellWidget(row, _COL_BTN)
            if w:
                w.setEnabled(not running)

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
        getattr(logging,
                level if level in ("debug", "info", "warning", "error", "critical") else "info")(msg)

    @Slot(str, dict)
    def _on_status(self, key: str, stats: dict):
        row = self._key_to_row.get(key)
        if row is None:
            return
        self.detail.item(row, _COL_FOUND).setText(str(stats.get("discovered", "—")))
        self.detail.item(row, _COL_NEW).setText(str(stats.get("new", 0)))
        self.detail.item(row, _COL_SKIP).setText(str(stats.get("skipped", 0)))
        self.detail.item(row, _COL_FAIL).setText(str(stats.get("failed", 0)))

    @Slot(str, str, int, int)
    def _on_progress(self, key: str, title: str, idx: int, total: int):
        self._lbl_progress.setText(f"Scraping: {key} — {title}  ({idx}/{total})")
        self._progress.setValue(int(idx * 100 / total) if total else 0)
