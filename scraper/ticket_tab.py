# scraper/ticket_tab.py
"""Tab 3 — Ticket Portal Scraper (v3.1).

Lets the user enter ticket IDs (single / comma-list / N-M range),
portal URL, username, and masked password, then scrapes each ticket
from support.contoso.example and saves JSON+MD to library/tickets/.

Security:
  - Password is stored only in OS keyring (Windows Credential Manager).
  - Password is never written to any file, never emitted to any log.
  - QLineEdit.Password echo mode masks the field at all times.
"""
from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
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
    QCheckBox,
    QSizePolicy,
)

import scraper.ticket_settings as ts
from scraper.ticket_engine import (
    CancellationToken,
    TicketEngineCallbacks,
    parse_ticket_input,
    run_ticket_scrape,
    TICKETS_DIR,
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


class _TicketWorker(QThread):
    def __init__(self, portal_url, username, password, ticket_ids, force, cancel,
                 workers=1, parent=None):
        super().__init__(parent)
        self._portal_url = portal_url
        self._username   = username
        self._password   = password   # held in memory only while thread is alive
        self._ticket_ids = ticket_ids
        self._force      = force
        self._cancel     = cancel
        self._workers    = workers
        self.signals     = _TicketSignals()

    def run(self):
        cb = TicketEngineCallbacks(
            on_log      = lambda lvl, msg: self.signals.log_sig.emit(lvl, msg),
            on_progress = lambda i, n:     self.signals.progress_sig.emit(i, n),
            on_ticket   = lambda tid, st:  self.signals.ticket_sig.emit(tid, st),
            on_finished = lambda rep:      self.signals.finished_sig.emit(rep),
        )
        try:
            run_ticket_scrape(
                portal_url = self._portal_url,
                username   = self._username,
                password   = self._password,
                ticket_ids = self._ticket_ids,
                force      = self._force,
                cancel     = self._cancel,
                cb         = cb,
                workers    = self._workers,
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
        self._cancel  = CancellationToken()
        self._ticket_rows: dict[str, int] = {}   # ticket_id -> table row

        self._build_ui()
        self._load_saved_settings()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        outer.addWidget(self._build_credentials_box())
        outer.addWidget(self._build_ticket_input_box())
        outer.addWidget(self._build_controls_row())
        outer.addWidget(self._build_progress_row())
        outer.addWidget(self._build_results_section(), stretch=1)

    def _build_credentials_box(self) -> QGroupBox:
        box = QGroupBox("Portal Credentials")
        g = QVBoxLayout(box)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Portal URL:"))
        self.inp_url = QLineEdit()
        self.inp_url.setPlaceholderText("https://support.contoso.example")
        self.inp_url.setMinimumWidth(280)
        row1.addWidget(self.inp_url, stretch=1)
        g.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Username:"))
        self.inp_user = QLineEdit()
        self.inp_user.setPlaceholderText("user@contoso.example")
        row2.addWidget(self.inp_user, stretch=1)
        g.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Password:"))
        self.inp_pass = QLineEdit()
        self.inp_pass.setEchoMode(QLineEdit.Password)
        self.inp_pass.setPlaceholderText("Password (stored in Windows Credential Manager)")
        row3.addWidget(self.inp_pass, stretch=1)
        g.addLayout(row3)

        save_row = QHBoxLayout()
        self.btn_save_creds = QPushButton("Save Credentials")
        self.btn_save_creds.setToolTip(
            "Saves URL+username to disk; password goes to Windows Credential Manager only."
        )
        self.btn_save_creds.clicked.connect(self._save_credentials)
        self.lbl_keyring = QLabel("")
        save_row.addWidget(self.btn_save_creds)
        save_row.addWidget(self.lbl_keyring)
        save_row.addStretch()
        g.addLayout(save_row)

        return box

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

    def _build_controls_row(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        # ── Button / workers row ──────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)

        self.btn_start = QPushButton("Start Scrape")
        self.btn_start.setStyleSheet(
            "QPushButton { background: #1b5e20; color: white; font-weight: bold; "
            "padding: 6px 18px; border-radius: 4px; } "
            "QPushButton:disabled { background: #aaa; }"
        )
        self.btn_start.clicked.connect(self._start)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._stop)

        lbl_workers = QLabel("Workers:")
        self.spn_workers = QSpinBox()
        self.spn_workers.setRange(1, 4)
        self.spn_workers.setValue(1)
        self.spn_workers.setToolTip(
            "Number of parallel Chrome windows (1–4).\n"
            "Each worker logs in independently. Use 2–4 for large batches."
        )
        self.spn_workers.setFixedWidth(52)

        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        btn_row.addSpacing(20)
        btn_row.addWidget(lbl_workers)
        btn_row.addWidget(self.spn_workers)
        btn_row.addStretch()
        v.addLayout(btn_row)

        # ── Output path label (separate line so it never crowds the spinner) ──
        self.lbl_output = QLabel(f"Output: {TICKETS_DIR}")
        self.lbl_output.setStyleSheet("color: #777; font-size: 10px;")
        v.addWidget(self.lbl_output)

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

        # Results table (top half)
        v.addWidget(QLabel("<b>Results</b>"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Ticket #", "Status", "Title"])
        self.table.horizontalHeader().setStretchLastSection(True)
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

    # ── Settings persistence ──────────────────────────────────────────────────

    def _load_saved_settings(self):
        settings = ts.load()
        self.inp_url.setText(settings.get("portal_url", "https://support.contoso.example"))
        username = settings.get("username", "")
        self.inp_user.setText(username)

        if username:
            pwd = ts.load_password(username)
            if pwd:
                self.inp_pass.setText(pwd)
                self.lbl_keyring.setText("✓ Password loaded from Credential Manager")
                self.lbl_keyring.setStyleSheet("color: #2e7d32;")
            else:
                self.lbl_keyring.setText("No saved password — enter and save.")
                self.lbl_keyring.setStyleSheet("color: #e65100;")
        else:
            self.lbl_keyring.setText("")

    def _save_credentials(self):
        url      = self.inp_url.text().strip()
        username = self.inp_user.text().strip()
        password = self.inp_pass.text()

        if not url or not username:
            QMessageBox.warning(self, "Missing Fields", "Portal URL and username are required.")
            return

        ts.save(url, username)
        self._emit_log("info", "Credentials saved (URL+username to disk).")

        if password:
            if ts.save_password(username, password):
                self.lbl_keyring.setText("✓ Password saved to Credential Manager")
                self.lbl_keyring.setStyleSheet("color: #2e7d32;")
                self._emit_log("info", "Password stored in Windows Credential Manager.")
            else:
                self.lbl_keyring.setText("⚠ Keyring unavailable — re-enter each session")
                self.lbl_keyring.setStyleSheet("color: #e65100;")
                self._emit_log("warning", "Keyring unavailable; password was not persisted.")
        else:
            self._emit_log("warning", "No password entered — not saved.")

    # ── Ticket input parsing ──────────────────────────────────────────────────

    def _on_ticket_input_changed(self, text: str):
        ids = parse_ticket_input(text)
        self.lbl_parsed.setText(f"{len(ids)} ticket{'s' if len(ids) != 1 else ''} parsed")

    # ── Scrape lifecycle ──────────────────────────────────────────────────────

    def _start(self):
        if self._worker and self._worker.isRunning():
            self._emit_log("warning", "A scrape is already running.")
            return

        # Validate inputs
        portal_url = self.inp_url.text().strip()
        username   = self.inp_user.text().strip()
        password   = self.inp_pass.text()
        raw_ids    = self.inp_tickets.text().strip()

        if not portal_url:
            QMessageBox.warning(self, "Missing Field", "Please enter the portal URL.")
            return
        if not username:
            QMessageBox.warning(self, "Missing Field", "Please enter your username.")
            return
        if not password:
            QMessageBox.warning(self, "Missing Field",
                "Please enter your password.\n\n"
                "If you saved it previously, it should be pre-filled. "
                "Otherwise type it and click 'Save Credentials'.")
            return
        if not raw_ids:
            QMessageBox.warning(self, "Missing Field",
                "Please enter at least one ticket number.")
            return

        ticket_ids = parse_ticket_input(raw_ids)
        if not ticket_ids:
            QMessageBox.warning(self, "No Tickets",
                "Could not parse any ticket IDs from the input.")
            return

        # Prepare table
        self.table.setRowCount(0)
        self._ticket_rows.clear()
        for tid in ticket_ids:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(f"#{tid}"))
            item_status = QTableWidgetItem("Queued")
            item_status.setForeground(QColor("#616161"))
            self.table.setItem(row, 1, item_status)
            self.table.setItem(row, 2, QTableWidgetItem(""))
            self._ticket_rows[tid] = row

        self._cancel = CancellationToken()
        force    = self.chk_force.isChecked()
        workers  = self.spn_workers.value()

        self._worker = _TicketWorker(portal_url, username, password, ticket_ids, force, self._cancel,
                                     workers=workers)
        self._worker.signals.log_sig.connect(self._emit_log)
        self._worker.signals.progress_sig.connect(self._on_progress)
        self._worker.signals.ticket_sig.connect(self._on_ticket_done)
        self._worker.signals.finished_sig.connect(self._on_finished)
        self._worker.finished.connect(self._worker_thread_done)

        self._set_running(True)
        self._emit_log("info", f"--- Starting ticket scrape: {len(ticket_ids)} tickets ---")
        self._worker.start()

    def _stop(self):
        if self._worker and self._worker.isRunning():
            self._cancel.cancel()
            self._emit_log("warning", "Stop requested — finishing current ticket then stopping.")

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
        getattr(log, level if level in ("debug","info","warning","error") else "info")(msg)

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

    @Slot(dict)
    def _on_finished(self, report: dict):
        saved      = report.get("saved", 0)
        skipped    = report.get("skipped", 0)
        not_found  = report.get("not_found", 0)
        failed     = report.get("failed", 0)
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
        self.btn_stop.setEnabled(running)
        self.btn_save_creds.setEnabled(not running)
        self.spn_workers.setEnabled(not running)
        self.inp_url.setReadOnly(running)
        self.inp_user.setReadOnly(running)
        self.inp_pass.setReadOnly(running)
        self.inp_tickets.setReadOnly(running)
