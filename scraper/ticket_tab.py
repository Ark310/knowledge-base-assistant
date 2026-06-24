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

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
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
import scraper.ticket_settings as ts
from scraper.control import RunControl
from scraper.settings_dialog import SettingsDialog
from scraper.ticket_engine import (
    TicketEngineCallbacks,
    parse_ticket_input,
    run_ticket_scrape,
)

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


# ── Worker thread ─────────────────────────────────────────────────────────────

class _TicketSignals(QObject):
    log_sig      = Signal(str, str)          # level, message
    progress_sig = Signal(int, int)          # current, total
    ticket_sig   = Signal(str, str)          # ticket_id, status
    finished_sig = Signal(dict)              # report
    meta_sig     = Signal(str, str, int)     # ticket_id, title, files_count


class _TicketWorker(QThread):
    def __init__(self, portal_url, username, password, ticket_ids, force,
                 control, workers=4, output_dir=None, parent=None):
        super().__init__(parent)
        self._portal_url = portal_url
        self._username   = username
        self._password   = password   # held in memory only while thread is alive
        self._ticket_ids = ticket_ids
        self._force      = force
        self._control    = control
        self._workers    = workers
        self._output_dir = output_dir
        self.signals     = _TicketSignals()

    def run(self):
        cb = TicketEngineCallbacks(
            on_log      = lambda lvl, msg: self.signals.log_sig.emit(lvl, msg),
            on_progress = lambda i, n:     self.signals.progress_sig.emit(i, n),
            on_ticket   = lambda tid, st:  self.signals.ticket_sig.emit(tid, st),
            on_finished = lambda rep:      self.signals.finished_sig.emit(rep),
            on_ticket_meta = lambda tid, title, n: self.signals.meta_sig.emit(tid, title, n),
        )
        try:
            run_ticket_scrape(
                portal_url = self._portal_url,
                username   = self._username,
                password   = self._password,
                ticket_ids = self._ticket_ids,
                force      = self._force,
                control    = self._control,
                cb         = cb,
                workers    = self._workers,
                output_dir = self._output_dir,
            )
        except Exception as exc:
            log.exception("TicketWorker crashed")
            self.signals.log_sig.emit("error", f"Ticket scraper crashed: {exc}")
            self.signals.finished_sig.emit({})
        finally:
            self._password = ""   # clear from memory as soon as we're done


# ── Tab widget ────────────────────────────────────────────────────────────────

class TicketTab(QWidget):
    """Tab 3 — Ticket Portal Scraper."""

    MAX_LOG_LINES = 3000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker: _TicketWorker | None = None
        self._control = RunControl()
        self._ticket_rows: dict[str, int] = {}   # ticket_id -> table row

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
        if self._worker and self._worker.isRunning():
            self._emit_log("warning", "A scrape is already running.")
            return

        # Read credentials from settings + keyring at run time (never from tab fields)
        settings   = ts.load()
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
            return

        raw_ids = self.inp_tickets.text().strip()
        if not raw_ids:
            QMessageBox.warning(self, "Missing Field",
                "Please enter at least one ticket number.")
            return

        ticket_ids = parse_ticket_input(raw_ids)
        if not ticket_ids:
            QMessageBox.warning(self, "No Tickets",
                "Could not parse any ticket IDs from the input.")
            return

        # Prepare table rows
        self.table.setRowCount(0)
        self._ticket_rows.clear()
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

        self._worker = _TicketWorker(
            portal_url, username, password, ticket_ids, force,
            control=self._control, workers=workers, output_dir=output_dir,
        )
        self._worker.signals.log_sig.connect(self._emit_log)
        self._worker.signals.progress_sig.connect(self._on_progress)
        self._worker.signals.ticket_sig.connect(self._on_ticket_done)
        self._worker.signals.finished_sig.connect(self._on_finished)
        self._worker.signals.meta_sig.connect(self._on_ticket_meta)
        self._worker.finished.connect(self._worker_thread_done)

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

    @Slot(str, str)
    def _emit_log(self, level: str, msg: str):
        ts_str = datetime.now().strftime("%H:%M:%S")
        line   = f"{ts_str} {level.upper():7s} {msg}"
        cursor = self.log_pane.textCursor()
        fmt    = QTextCharFormat()
        color_map = {
            "error":   "#c62828",
            "warning": "#ef6c00",
            "info":    "#212121",
        }
        fmt.setForeground(QColor(color_map.get(level, "#616161")))
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(line + "\n", fmt)
        self.log_pane.setTextCursor(cursor)
        self.log_pane.ensureCursorVisible()
        getattr(log, level if level in ("debug", "info", "warning", "error") else "info")(msg)

    @Slot(int, int)
    def _on_progress(self, current: int, total: int):
        pct = int(current * 100 / total) if total else 0
        self.progress.setValue(pct)
        self.lbl_progress.setText(f"Ticket {current} / {total}")

    @Slot(str, str)
    def _on_ticket_done(self, tid: str, status: str):
        row = self._ticket_rows.get(tid)
        if row is None:
            return
        label = _STATUS_LABELS.get(status, status.title())
        color = _STATUS_COLORS.get(status, "#000")
        item  = QTableWidgetItem(label)
        item.setForeground(QColor(color))
        self.table.setItem(row, 1, item)

    @Slot(str, str, int)
    def _on_ticket_meta(self, tid: str, title: str, files: int):
        """Populate Title (col 2) and Files (col 3) for a completed ticket row."""
        row = self._ticket_rows.get(tid)
        if row is None:
            return
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
        self._set_running(False)
        self.lbl_progress.setText("Idle")
        self.progress.setValue(0)

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
