# scraper/kb_tab.py — Option C: families sidebar + per-family detail table
from __future__ import annotations
import json
import logging

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QListWidget, QTableWidget, QComboBox, QSpinBox,
    QTableWidgetItem, QSplitter, QLineEdit, QHeaderView, QMessageBox,
)

import scraper.config as config
from scraper.config import STATE_DIR
from scraper.kb_config import KB_PRODUCT_GROUPS, KB_SPACES, KB_SPACES_BY_KEY
from scraper.kb_engine import KBEngine, KB_REPORT_FILE
from scraper.kb_audit import audit_spaces
from scraper.engine import Engine, EngineCallbacks, CancellationToken
from scraper.control import RunControl
from scraper.log_pane import LogPane
from scraper.async_runner import AsyncKBWorker
import scraper.app_settings as app_settings
import scraper.run_registry as run_registry

# Standalone Audit Library report (separate from the scrape engine's own
# KB_REPORT_FILE) — read alongside it when building the Retry Failures set.
KB_AUDIT_REPORT_FILE = STATE_DIR / "kb_audit_report.json"


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


class _AuditWorker(QThread):
    """Audit Library — discovery-only completeness check, no browser
    (v4.0.4 Task 7). Runs on a small QThread so live discovery calls don't
    block the GUI; registry-guarded the same way scrape actions are."""
    result_ready = Signal(dict)

    def __init__(self, space_cfgs, output_base):
        super().__init__()
        self._space_cfgs = space_cfgs
        self._output_base = output_base

    def run(self):
        try:
            result = audit_spaces(self._space_cfgs, self._output_base)
        except Exception as exc:
            logging.exception("KB audit crashed")
            result = {"spaces": {}, "error": type(exc).__name__,
                      "totals": {"discovered": 0, "on_disk": 0, "missing": 0,
                                 "spaces_with_errors": 0}}
        self.result_ready.emit(result)


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
        self._run_name = "Knowledge Base"
        self._alert_box = None

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

        self.worker: QThread | None = None

        # Family map: label -> [{key, display_name, engine_kind}]
        self._families: dict[str, list[dict]] = _make_family_map()

        # key -> detail row index (repopulated on each family selection)
        self._key_to_row: dict[str, int] = {}

        # Reapply process priority periodically while a run is active — Chrome
        # spawns new child processes over time and each needs the level applied
        # (mirrors TicketTab).
        self._prio_timer = QTimer(self)
        self._prio_timer.setInterval(5000)
        self._prio_timer.timeout.connect(self._reapply_priority)

        self._build_ui()
        self._wire_signals()
        # Ceiling for the live worker slider (mirrors TicketTab Fix 3): parking
        # can only lower/restore workers within the run's STARTING count —
        # raising above it is a no-op until the next run.
        self._run_workers = self.spn_workers.value()
        self._set_running(False)
        self._refresh_retry_enabled()
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
        self.btn_retry      = QPushButton("Retry Failures")
        self.btn_retry.setToolTip(
            "Re-scrape exactly the articles that failed or came up missing in "
            "an Audit — dedup'd across the last run's report and the last "
            "library audit.")
        self.btn_audit      = QPushButton("Audit Library")
        self.btn_audit.setToolTip(
            "Discovery-only completeness check: compares what's live against "
            "what's on disk (no browser, no scraping).")
        self.btn_pause      = QPushButton("Pause")
        self.btn_stop       = QPushButton("Stop")
        self.inp_filter     = QLineEdit()
        self.inp_filter.setPlaceholderText("Filter spaces…")
        self.inp_filter.setMaximumWidth(180)
        for w in (self.btn_validate, self.btn_rebuild, self.btn_scrape_all,
                  self.btn_force_all, self.btn_retry, self.btn_audit,
                  self.btn_pause, self.btn_stop):
            top.addWidget(w)
        top.addStretch()
        top.addWidget(self.inp_filter)
        outer.addLayout(top)

        outer.addWidget(self._build_workers_row())

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

        # ── Resource monitor (v4.0.4 Task 7) ────────────────────────────────
        # Mounted between the progress bar and the log, mirroring TicketTab.
        try:
            from scraper.resmon import ResourceSampler
            self._sampler = ResourceSampler()
        except Exception:
            self._sampler = None
        from scraper.resource_monitor import ResourceMonitorWidget
        self.monitor = ResourceMonitorWidget(sampler=self._sampler)
        outer.addWidget(self.monitor)
        self.monitor.start()

        # ── Log pane ──────────────────────────────────────────────────────────
        # Buffered/colorized widget shared with TicketTab (bug-144 fix; see
        # scraper/log_pane.py) — replaces the old per-line insertText path,
        # which lagged under a fast-emitting run the same way TicketTab's did.
        outer.addWidget(QLabel("<b>Log</b>"))
        self.log_pane = LogPane(max_lines=self.MAX_LOG_LINES)
        outer.addWidget(self.log_pane, stretch=1)

    def _build_workers_row(self) -> QWidget:
        """Workers 1–10 + priority combo — mirrors TicketTab's exact pattern
        (v4.0.4 Task 7)."""
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 4, 0, 4)

        lbl = QLabel("Workers (1–10):")
        lbl.setStyleSheet("font-weight: bold;")

        self.spn_workers = QSpinBox()
        self.spn_workers.setRange(1, 10)
        self.spn_workers.setValue(4)
        self.spn_workers.setMinimumWidth(64)
        self.spn_workers.setToolTip(
            "Number of parallel tabs sharing one Chrome window for KB scraping "
            "(1–10).\nWhile a scrape is running, lowering this pauses (parks) "
            "the extra workers immediately. Raising it above the run's "
            "starting count has no effect until the next run.")

        lbl_hint = QLabel("parallel workers")
        lbl_hint.setStyleSheet("color: #777;")

        row.addWidget(lbl)
        row.addWidget(self.spn_workers)
        row.addWidget(lbl_hint)

        row.addSpacing(24)
        lbl_p = QLabel("Priority:")
        lbl_p.setStyleSheet("font-weight: bold;")
        self.cmb_priority = QComboBox()
        self.cmb_priority.addItems(["Low", "Normal", "High"])
        self.cmb_priority.setCurrentText(app_settings.priority().title())
        self.cmb_priority.setToolTip(
            "Windows process priority for the scraper and its Chrome processes.\n"
            "High = faster on a busy machine.")
        self.cmb_priority.currentTextChanged.connect(self._on_priority_changed)
        row.addWidget(lbl_p)
        row.addWidget(self.cmb_priority)

        row.addStretch()
        return w

    def _wire_signals(self):
        self._bridge.log_sig.connect(self._log)
        self._bridge.status_sig.connect(self._on_status)
        self._bridge.progress_sig.connect(self._on_progress)

        self.rail.currentTextChanged.connect(self._populate_detail)

        self.btn_validate.clicked.connect(lambda: self._start_kb("validate"))
        self.btn_rebuild.clicked.connect(lambda: self._start_kb("rebuild_indexes"))
        self.btn_scrape_all.clicked.connect(self._scrape_all_action)
        self.btn_force_all.clicked.connect(self._force_all_action)
        self.btn_retry.clicked.connect(self._on_retry_clicked)
        self.btn_audit.clicked.connect(self._start_audit)
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_stop.clicked.connect(self._stop)
        self._btn_scrape_fam.clicked.connect(lambda: self._scrape_family(force=False))
        self._btn_force_fam.clicked.connect(lambda: self._scrape_family(force=True))
        self.inp_filter.textChanged.connect(self._filter_detail)
        self.spn_workers.valueChanged.connect(self._on_workers_changed)

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

        running = bool(self.worker and self.worker.isRunning())

        # Insert ALL rows and register every key so status updates are never
        # lost mid-run — then call _filter_detail() to hide non-matching rows.
        for sp in spaces:
            row = self.detail.rowCount()
            self.detail.insertRow(row)
            self._key_to_row[sp["key"]] = row

            self.detail.setItem(row, 0, QTableWidgetItem(sp["display_name"]))
            for col in (_COL_FOUND, _COL_NEW, _COL_SKIP, _COL_FAIL):
                self.detail.setItem(row, col, QTableWidgetItem("—"))

            btn = QPushButton("Scrape")
            btn.setEnabled(not running)
            # capture loop vars
            key = sp["key"]
            kind = sp["engine_kind"]
            btn.clicked.connect(lambda _=False, k=key, kd=kind: self._scrape_space(k, kd, force=False))
            self.detail.setCellWidget(row, _COL_BTN, btn)

        self._filter_detail(self.inp_filter.text())

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

    def _try_acquire_run(self) -> bool:
        """Single-run guard (R7) — only one scrape across ALL tabs. Shows the same
        warning dialog TicketTab shows on refusal."""
        if run_registry.acquire(self._run_name):
            return True
        QMessageBox.warning(
            self, "Another scrape is running",
            f"A scrape is already running on '{run_registry.owner()}'.\n"
            "Only one scrape can run at a time — wait for it to finish or stop it.")
        return False

    def _start_kb(self, action: str, kwargs: dict | None = None):
        """Dispatch a KBEngine action."""
        if not self._try_acquire_run():
            return
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
        if not self._try_acquire_run():
            return
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
            cfg = KB_SPACES_BY_KEY.get(key)
            if cfg is None:
                return
            self._start_kb_async(space_cfgs=[cfg], force=force)
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
        # All spaces in a KB family use AsyncKBWorker; RN family uses v1 Engine.
        # Use the FULL KB_PRODUCT_GROUPS cfg dicts (product/lib_folder/display_name)
        # — self._families only carries the rail's slim {key, display_name,
        # engine_kind} shape, which the engine can't scrape with.
        if spaces[0]["engine_kind"] == "kb":
            self._start_kb_async(space_cfgs=KB_PRODUCT_GROUPS.get(label, []), force=force)
        else:
            self._start_rn("scrape_all", {"force": force})

    def _scrape_all_action(self):
        """Scrape KB scrape_all (async) then RN scrape_all (chained)."""
        self._start_kb_async(space_cfgs=KB_SPACES, force=False, chain_rn=True)

    def _force_all_action(self):
        """Force-scrape KB (async) + RN (chained)."""
        self._start_kb_async(space_cfgs=KB_SPACES, force=True, chain_rn=True)

    def _start_kb_async(self, *, space_cfgs, force, items=None, chain_rn=False):
        """Dispatch a KB engine action through AsyncKBWorker (v4.0.4 Task 7) —
        used for scrape_space/scrape_family/scrape_all's KB half/Retry Failures.
        Validate and Rebuild Indexes stay on the old synchronous KBEngine path
        (_start_kb)."""
        if not self._try_acquire_run():
            return
        if self.worker and self.worker.isRunning():
            self._log("warning", "A run is already in progress.")
            return
        self._fresh_control()
        workers = self.spn_workers.value()
        self._run_workers = workers
        worker = AsyncKBWorker(
            space_cfgs, force=force, workers=workers,
            output_base=app_settings.kb_dir(), control=self._control, items=items,
        )
        worker.log.connect(self._log)
        worker.status.connect(self._on_status)
        worker.progress.connect(self._on_progress)
        worker.alert.connect(self._on_alert)
        if chain_rn:
            worker.finished.connect(lambda: self._kb_done_start_rn(force=force))
        else:
            worker.finished.connect(self._worker_done)
        self.worker = worker
        self._set_running(True)
        self.monitor.reset_run()
        self.monitor.set_workers_info(workers)
        if items is not None:
            self._log("info", f"--- Retry Failures: {len(items)} article(s) "
                       f"({workers} worker(s)) ---")
        elif chain_rn:
            self._log("info", f"--- {'Force' if force else 'Scrape'} All: KB "
                       f"(async, {workers} worker(s)) + Release Notes next ---")
        else:
            self._log("info", f"--- KB scrape (async, {workers} worker(s)) ---")
        worker.start()
        # Chrome children spawn a moment after the worker starts; the 5s
        # _prio_timer (started in _set_running) reapplies for those stragglers.
        self._on_priority_changed(self.cmb_priority.currentText())

    # ── Retry Failures ────────────────────────────────────────────────────────

    def _collect_retry_candidates(self) -> list[dict]:
        """Union of the last scrape's failed_articles + audit-missing (from
        BOTH KB_REPORT_FILE's embedded audit and the standalone Audit Library
        report), deduped by space_key|slug. Missing/corrupt report files are
        silently treated as empty — never crash the UI."""
        def _load(path) -> dict:
            try:
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
            return {}

        seen: dict[str, dict] = {}

        def _add(item: dict):
            sk, slug = item.get("space_key"), item.get("slug")
            if sk and slug and sk in KB_SPACES_BY_KEY:
                seen[f"{sk}|{slug}"] = item

        report = _load(KB_REPORT_FILE)
        for item in report.get("failed_articles") or []:
            _add(item)
        for source in (report.get("audit"), _load(KB_AUDIT_REPORT_FILE)):
            for entry in ((source or {}).get("spaces") or {}).values():
                for item in entry.get("missing") or []:
                    _add(item)

        return list(seen.values())

    def _retry_available(self) -> bool:
        return bool(self._collect_retry_candidates())

    def _refresh_retry_enabled(self, running: bool | None = None):
        if running is None:
            running = bool(self.worker and self.worker.isRunning())
        self.btn_retry.setEnabled((not running) and self._retry_available())

    def _on_retry_clicked(self):
        candidates = self._collect_retry_candidates()
        if not candidates:
            return
        items = [(KB_SPACES_BY_KEY[c["space_key"]], c) for c in candidates]
        self._start_kb_async(space_cfgs=[], force=True, items=items)

    # ── Audit Library ─────────────────────────────────────────────────────────

    def _start_audit(self):
        if not self._try_acquire_run():
            return
        if self.worker and self.worker.isRunning():
            self._log("warning", "A run is already in progress.")
            return
        self._log("info", "--- Starting: Audit Library ---")
        worker = _AuditWorker(KB_SPACES, app_settings.kb_dir())
        worker.result_ready.connect(self._on_audit_result)
        worker.finished.connect(self._worker_done)
        self.worker = worker
        self._set_running(True)
        worker.start()

    @Slot(dict)
    def _on_audit_result(self, result: dict):
        try:
            KB_AUDIT_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
            KB_AUDIT_REPORT_FILE.write_text(json.dumps(result, indent=2), encoding="utf-8")
        except Exception as exc:
            self._log("error", f"KB audit report write failed ({type(exc).__name__}).")
        self._refresh_retry_enabled()
        totals = result.get("totals") or {}
        missing = totals.get("missing", 0)
        errors = totals.get("spaces_with_errors", 0)
        if missing or errors:
            self._on_alert("warning", "KB library audit — items need attention",
                f"WHAT HAPPENED: {missing} article(s) missing on disk"
                + (f" and {errors} space(s) hit discovery errors" if errors else "")
                + ".\nWHAT TO DO: click 'Retry Failures' to re-scrape exactly "
                "those articles.")
        else:
            discovered = totals.get("discovered", 0)
            self._on_alert("info", "KB library audit — all clear",
                f"All {discovered} discovered article(s) are present on disk.")

    @Slot()
    def _kb_done_start_rn(self, force: bool = False):
        """Called when KB scrape_all finishes; starts RN scrape_all next.

        Still the same logical run as _scrape_all_action/_force_all_action (which
        already hold the registry) — reacquiring here is a same-owner no-op and
        only guards the (unreachable in practice) case where ownership was lost
        mid-chain.
        """
        if self._control.is_cancelled():
            self._worker_done()
            return
        if not self._try_acquire_run():
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
        run_registry.release(self._run_name)
        self._set_running(False)
        self._log("info", "--- Run complete ---")
        self._lbl_progress.setText("Idle")
        self._progress.setValue(0)
        self.btn_pause.setText("Pause")

    def _set_running(self, running: bool):
        for btn in (self.btn_validate, self.btn_rebuild, self.btn_scrape_all,
                    self.btn_force_all, self._btn_scrape_fam, self._btn_force_fam,
                    self.btn_audit):
            btn.setEnabled(not running)
        self._refresh_retry_enabled(running)
        self.btn_pause.setEnabled(running)
        self.btn_stop.setEnabled(running)
        self._prio_timer.start() if running else self._prio_timer.stop()
        # per-space scrape buttons in the detail table
        for row in range(self.detail.rowCount()):
            w = self.detail.cellWidget(row, _COL_BTN)
            if w:
                w.setEnabled(not running)

    # ── Priority control ─────────────────────────────────────────────────────

    def _on_priority_changed(self, text: str):
        level = text.strip().lower()
        app_settings.set_priority(level)
        from scraper import procctl
        n = procctl.apply_priority(level)
        self._log("info", f"Process priority set to {text} ({n} process(es)).")

    def _reapply_priority(self):
        from scraper import procctl
        procctl.apply_priority(app_settings.priority())

    # ── Live worker slider ───────────────────────────────────────────────────

    def _on_workers_changed(self, value: int):
        if isinstance(self.worker, AsyncKBWorker) and self.worker.isRunning():
            # Parking can only lower/restore workers within the run's STARTING
            # count (self._run_workers) — raising above that ceiling doesn't
            # spawn new workers mid-run. Show the operator the EFFECTIVE
            # (clamped) value so the UI never claims more workers are active
            # than actually are (mirrors TicketTab final-review Fix 3).
            effective = min(value, self._run_workers)
            self._control.target_workers = value
            self.monitor.set_workers_info(effective)
            suffix = "" if effective == value else f" — max {self._run_workers} this run"
            self._log("info", f"Workers target changed to {effective} (live{suffix}).")

    # ── Slots ─────────────────────────────────────────────────────────────────

    @Slot(str, str)
    def _log(self, level: str, msg: str):
        """Delegates to the shared LogPane (bug-144 buffered-flush fix; see
        scraper/log_pane.py). LogPane owns the logging-forward now — it logs
        to the "scraper" logger (TicketTab's logger; this tab previously used
        the root `logging` module directly, now unified)."""
        self.log_pane.emit_log(level, msg)

    @Slot(str, dict)
    def _on_status(self, key: str, stats: dict):
        row = self._key_to_row.get(key)
        if row is None:
            # Space belongs to a family not currently shown (e.g. during Scrape All) — intentionally ignored.
            return
        self.detail.item(row, _COL_FOUND).setText(str(stats.get("discovered", "—")))
        self.detail.item(row, _COL_NEW).setText(str(stats.get("new", 0)))
        self.detail.item(row, _COL_SKIP).setText(str(stats.get("skipped", 0)))
        self.detail.item(row, _COL_FAIL).setText(str(stats.get("failed", 0)))

    @Slot(str, str, int, int)
    def _on_progress(self, key: str, title: str, idx: int, total: int):
        self._lbl_progress.setText(f"Scraping: {key} — {title}  ({idx}/{total})")
        self._progress.setValue(int(idx * 100 / total) if total else 0)
        self.monitor.set_progress(idx, total)

    @Slot(str, str, str)
    def _on_alert(self, severity: str, title: str, body: str):
        if self._control.paused:
            self.btn_pause.setText("Resume")
        icon = QMessageBox.Critical if severity == "error" else QMessageBox.Warning
        box = QMessageBox(icon, title, body, QMessageBox.Ok, self)
        box.setWindowModality(Qt.NonModal)
        box.show()
        self._alert_box = box   # keep a ref so it isn't GC'd
