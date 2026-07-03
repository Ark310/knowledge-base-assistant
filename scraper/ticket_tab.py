# scraper/ticket_tab.py
"""Tab 3 — Ticket Portal Scraper (v4).

Lets the user enter ticket IDs (single / comma-list / N-M range) and scrapes
each ticket from the configured portal, saving JSON+MD to the output folder
set in app_settings.

Security:
  - Password is stored only in OS keyring (Windows Credential Manager).
  - Password is never entered, stored, or logged in this tab.
  - Credentials are read from ticket_settings + keyring at run time.
  - If credentials are missing the user is directed to open Settings.
"""
from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import scraper.app_settings as app_settings
import scraper.run_registry as run_registry
import scraper.ticket_settings as ts
from scraper.async_runner import AsyncTicketWorker
from scraper.control import RunControl
from scraper.settings_dialog import SettingsDialog
from scraper.ticket_engine import parse_ticket_input

log = logging.getLogger("scraper")

_STATUS_COLORS = {
    "ok":        "#2e7d32",
    "skipped":   "#1565c0",
    "not_found": "#e65100",
    "failed":    "#c62828",
}
_STATUS_LABELS = {
    "ok":        "Saved",
    "skipped":   "Skipped",
    "not_found": "Not Found",
    "failed":    "Failed",
}


# (AsyncTicketWorker imported from scraper.async_runner — no local worker class needed)


# ── Tab widget ────────────────────────────────────────────────────────────────

class TicketTab(QWidget):
    """Tab 3 — Ticket Portal Scraper."""

    MAX_LOG_LINES = 3000
    BIG_BATCH_ROWS = 2000  # batches larger than this skip row pre-creation (bug-115)

    def __init__(self, parent=None, *, portal_kind: str = "tradedesk", default_url: str | None = None):
        super().__init__(parent)
        self._portal_kind = portal_kind
        self._default_url = default_url
        self._worker: AsyncTicketWorker | None = None
        self._control = RunControl()
        self._ticket_rows: dict[str, int] = {}   # ticket_id -> table row
        self._run_name = f"Tickets — {portal_kind}"
        self._alert_box = None
        self._big_batch = False

        self._log_buf: list[tuple[str, str, str]] = []   # (ts, level, msg)
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(250)
        self._log_timer.timeout.connect(self._flush_log)
        self._log_timer.start()

        self._build_ui()
        self._refresh_creds_label()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        outer.addWidget(self._build_creds_status_row())
        outer.addWidget(self._build_ticket_input_box())
        outer.addWidget(self._build_workers_row())
        outer.addWidget(self._build_controls_row())
        outer.addWidget(self._build_progress_row())
        outer.addWidget(self._build_results_section(), stretch=1)

    def _build_creds_status_row(self) -> QWidget:
        """Status line showing current credentials + Settings button (no inline entry)."""
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)

        self.lbl_creds = QLabel("")
        self.lbl_creds.setWordWrap(True)

        self.btn_settings = QPushButton("⚙ Settings")
        self.btn_settings.setToolTip("Open Settings to configure portal credentials and output folders.")
        self.btn_settings.clicked.connect(self._open_settings)

        row.addWidget(self.lbl_creds, stretch=1)
        row.addWidget(self.btn_settings)
        return w

    def _build_ticket_input_box(self) -> QGroupBox:
        box = QGroupBox("Tickets to Scrape")
        g = QVBoxLayout(box)
        g.addWidget(QLabel(
            "Enter ticket numbers — single (74500), comma-separated (74500,74510), "
            "or range (74500-74515). Mix freely."
        ))
        self.inp_tickets = QLineEdit()
        self.inp_tickets.setPlaceholderText("e.g. 74500, 74510-74515, 74520")
        g.addWidget(self.inp_tickets)

        row = QHBoxLayout()
        self.lbl_parsed = QLabel("0 tickets parsed")
        self.inp_tickets.textChanged.connect(self._on_ticket_input_changed)
        self.chk_force = QCheckBox("Force re-scrape (skip already-scraped check)")
        row.addWidget(self.lbl_parsed)
        row.addStretch()
        row.addWidget(self.chk_force)
        g.addLayout(row)

        return box

    def _build_workers_row(self) -> QWidget:
        """Prominent, clearly-labelled Workers 1–10 row — given its own line."""
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
            "Number of parallel Chrome windows (1–10).\n"
            "Each worker logs in independently. Use 2–4 for large batches."
        )

        lbl_hint = QLabel("parallel workers")
        lbl_hint.setStyleSheet("color: #777;")

        row.addWidget(lbl)
        row.addWidget(self.spn_workers)
        row.addWidget(lbl_hint)
        row.addStretch()
        return w

    def _build_controls_row(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)

        self.btn_start = QPushButton("▶ Start Scrape")
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_start.clicked.connect(self._start)

        self.btn_pause = QPushButton("⏸ Pause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self._toggle_pause)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)

        row.addWidget(self.btn_start)
        row.addWidget(self.btn_pause)
        row.addWidget(self.btn_stop)
        row.addStretch()
        return w

    def _build_progress_row(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        self.lbl_progress = QLabel("Idle")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(18)
        row.addWidget(self.lbl_progress)
        row.addWidget(self.progress, stretch=1)
        return w

    def _build_results_section(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)

        # Results table (top half) — 4 columns: Ticket #, Status, Title, Files
        v.addWidget(QLabel("<b>Results</b>"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Ticket #", "Status", "Title", "Files"])
        hdr = self.table.horizontalHeader()
        hdr.setStretchLastSection(False)
        # Title column (2) stretches; others are sized to content
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setMaximumHeight(200)
        v.addWidget(self.table)

        # Log pane (bottom half)
        v.addWidget(QLabel("<b>Log</b>"))
        self.log_pane = QPlainTextEdit()
        self.log_pane.setReadOnly(True)
        self.log_pane.setMaximumBlockCount(self.MAX_LOG_LINES)
        self.log_pane.setFont(QFont("Consolas", 9))
        v.addWidget(self.log_pane, stretch=1)

        return w

    # ── Credentials status ────────────────────────────────────────────────────

    def _refresh_creds_label(self):
        """Update lbl_creds from ticket_settings (no password read — just URL+username)."""
        settings = ts.load()
        url      = settings.get("portal_url", "")
        username = settings.get("username", "")
        if url and username:
            self.lbl_creds.setText(f"Portal: {url}  ·  signed in as {username}")
            self.lbl_creds.setStyleSheet("color: #2e7d32;")
        else:
            self.lbl_creds.setText("Portal credentials not configured — open Settings")
            self.lbl_creds.setStyleSheet("color: #e65100;")

    def _open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()
        self._refresh_creds_label()

    # ── Ticket input parsing ──────────────────────────────────────────────────

    def _on_ticket_input_changed(self, text: str):
        ids = parse_ticket_input(text)
        self.lbl_parsed.setText(f"{len(ids)} ticket{'s' if len(ids) != 1 else ''} parsed")

    # ── Scrape lifecycle ──────────────────────────────────────────────────────

    def _start(self):
        if not run_registry.acquire(self._run_name):
            QMessageBox.warning(
                self, "Another scrape is running",
                f"A scrape is already running on '{run_registry.owner()}'.\n"
                "Only one scrape can run at a time — wait for it to finish or stop it.")
            return

        if self._worker and self._worker.isRunning():
            self._emit_log("warning", "A scrape is already running.")
            return

        # Read credentials from settings + keyring at run time (never from tab fields)
        # Both portals share the same keyring entry (ticket_settings).
        settings   = ts.load()
        # tradedesk uses the configured URL; contoso uses the legacy default URL
        if self._portal_kind == "contoso":
            portal_url = self._default_url or "https://support.contoso.example"
        else:
            portal_url = settings.get("portal_url", "").strip()
        username   = settings.get("username", "").strip()
        password   = ts.load_password(username) if username else ""

        if not (portal_url and username and password):
            QMessageBox.information(
                self, "Portal Credentials Required",
                "Configure portal credentials in Settings before starting a scrape.",
            )
            self._open_settings()
            self._refresh_creds_label()
            run_registry.release(self._run_name)
            return

        raw_ids = self.inp_tickets.text().strip()
        if not raw_ids:
            QMessageBox.warning(self, "Missing Field",
                "Please enter at least one ticket number.")
            run_registry.release(self._run_name)
            return

        ticket_ids = parse_ticket_input(raw_ids)
        if not ticket_ids:
            QMessageBox.warning(self, "No Tickets",
                "Could not parse any ticket IDs from the input.")
            run_registry.release(self._run_name)
            return

        # Prepare table rows. Pre-creating tens of thousands of QTableWidget rows
        # froze the UI (bug-115); large batches skip pre-creation and rows are
        # appended lazily (_row_for) as tickets complete.
        self.table.setRowCount(0)
        self._ticket_rows.clear()
        self._big_batch = len(ticket_ids) > self.BIG_BATCH_ROWS
        if self._big_batch:
            self._emit_log("info",
                f"Large batch ({len(ticket_ids)} tickets): results table fills as "
                "tickets complete.")
        else:
            for tid in ticket_ids:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(f"#{tid}"))
                item_status = QTableWidgetItem("Queued")
                item_status.setForeground(QColor("#616161"))
                self.table.setItem(row, 1, item_status)
                self.table.setItem(row, 2, QTableWidgetItem(""))   # Title — filled by meta_sig
                self.table.setItem(row, 3, QTableWidgetItem(""))   # Files — filled by meta_sig
                self._ticket_rows[tid] = row

        self._control    = RunControl()
        force            = self.chk_force.isChecked()
        workers          = self.spn_workers.value()
        output_dir       = app_settings.tickets_dir()

        mode = app_settings.browser_mode()
        headless = app_settings.headless()
        self._worker = AsyncTicketWorker(
            portal_url, username, password, ticket_ids,
            force=force, workers=workers, output_dir=output_dir,
            control=self._control, mode=mode, headless=headless,
            portal_kind=self._portal_kind,
        )
        self._worker.log.connect(self._emit_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.ticket.connect(self._on_ticket_done)
        self._worker.finished_report.connect(self._on_finished)
        self._worker.ticket_meta.connect(self._on_ticket_meta)
        self._worker.finished.connect(self._worker_thread_done)
        self._worker.alert.connect(self._on_alert)

        self._set_running(True)
        self._emit_log("info", f"--- Starting ticket scrape: {len(ticket_ids)} tickets ---")
        self._worker.start()

    def _toggle_pause(self):
        if self._control.paused:
            self._control.resume()
            self.btn_pause.setText("⏸ Pause")
            self._emit_log("info", "Scrape resumed.")
        else:
            self._control.pause()
            self.btn_pause.setText("▶ Resume")
            self._emit_log("info", "Scrape paused — will stop after current ticket.")

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self._control.cancel()
            self._emit_log("warning", "Stop requested — finishing current ticket then stopping.")

    def shutdown(self) -> None:
        """Cancel a running scrape and wait for the worker thread to exit.

        Called by MainWindow.closeEvent — a child widget's own closeEvent does NOT fire
        when the parent window closes. cancel() also releases a PAUSED worker blocked in
        RunControl.wait_if_paused(), so the QThread can return instead of being destroyed
        while still running.
        """
        if self._worker and self._worker.isRunning():
            self._control.cancel()
            self._worker.wait(15_000)

    # ── Slot handlers ─────────────────────────────────────────────────────────

    _LOG_COLORS = {"error": "#c62828", "warning": "#ef6c00", "info": "#212121"}

    @Slot(str, str)
    def _emit_log(self, level: str, msg: str):
        """Buffer only — a 30k-ticket run at 10 workers emits log lines faster
        than QPlainTextEdit can append+scroll one-by-one (bug-115 UI freeze).
        A 250ms timer (_flush_log) drains the buffer as ONE insert."""
        self._log_buf.append((datetime.now().strftime("%H:%M:%S"), level, msg))
        getattr(log, level if level in ("debug", "info", "warning", "error") else "info")(msg)

    def _flush_log(self):
        if not self._log_buf:
            return
        buf, self._log_buf = self._log_buf, []
        import html as _html
        parts = []
        for ts_str, level, msg in buf:
            color = self._LOG_COLORS.get(level, "#616161")
            # HTML collapses whitespace, so plain padding spaces would not keep
            # the level column aligned — use &nbsp; to preserve it.
            level_str = f"{level.upper():7s}".replace(" ", "&nbsp;")
            parts.append(f'<span style="color:{color}">'
                         f'{ts_str} {level_str} {_html.escape(msg)}</span>')
        self.log_pane.appendHtml("<br>".join(parts))
        self.log_pane.verticalScrollBar().setValue(
            self.log_pane.verticalScrollBar().maximum())

    @Slot(int, int)
    def _on_progress(self, current: int, total: int):
        pct = int(current * 100 / total) if total else 0
        self.progress.setValue(pct)
        self.lbl_progress.setText(f"Ticket {current} / {total}")

    def _row_for(self, tid: str) -> int:
        """Return the table row for tid, lazily appending one if it doesn't
        exist yet (big-batch mode never pre-creates rows — bug-115)."""
        row = self._ticket_rows.get(tid)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(f"#{tid}"))
            self.table.setItem(row, 1, QTableWidgetItem(""))
            self.table.setItem(row, 2, QTableWidgetItem(""))
            self.table.setItem(row, 3, QTableWidgetItem(""))
            self._ticket_rows[tid] = row
        return row

    @Slot(str, str)
    def _on_ticket_done(self, tid: str, status: str):
        row = self._row_for(tid)
        label = _STATUS_LABELS.get(status, status.title())
        color = _STATUS_COLORS.get(status, "#000")
        item  = QTableWidgetItem(label)
        item.setForeground(QColor(color))
        self.table.setItem(row, 1, item)

    @Slot(str, str, int)
    def _on_ticket_meta(self, tid: str, title: str, files: int):
        """Populate Title (col 2) and Files (col 3) for a completed ticket row."""
        row = self._row_for(tid)
        self.table.setItem(row, 2, QTableWidgetItem(title))
        self.table.setItem(row, 3, QTableWidgetItem(str(files)))

    @Slot(dict)
    def _on_finished(self, report: dict):
        saved     = report.get("saved", 0)
        skipped   = report.get("skipped", 0)
        not_found = report.get("not_found", 0)
        failed    = report.get("failed", 0)
        self._emit_log("info",
            f"--- Done: {saved} saved, {skipped} skipped, "
            f"{not_found} not found, {failed} failed ---"
        )

    @Slot()
    def _worker_thread_done(self):
        run_registry.release(self._run_name)
        self._set_running(False)
        self.lbl_progress.setText("Idle")
        self.progress.setValue(0)

    @Slot(str, str, str)
    def _on_alert(self, severity: str, title: str, body: str):
        if self._control.paused:
            self.btn_pause.setText("▶ Resume")
        icon = QMessageBox.Critical if severity == "error" else QMessageBox.Warning
        box = QMessageBox(icon, title, body, QMessageBox.Ok, self)
        box.setWindowModality(Qt.NonModal)
        box.show()
        self._alert_box = box   # keep a ref so it isn't GC'd

    # ── UI state helpers ──────────────────────────────────────────────────────

    def _set_running(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_pause.setEnabled(running)
        self.btn_stop.setEnabled(running)
        self.btn_settings.setEnabled(not running)
        self.spn_workers.setEnabled(not running)
        self.inp_tickets.setReadOnly(running)
        self.chk_force.setEnabled(not running)
        if not running:
            # Reset pause button label for next run
            self.btn_pause.setText("⏸ Pause")
