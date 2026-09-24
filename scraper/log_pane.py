# scraper/log_pane.py
"""Shared buffered log widget (v4.0.4, Task 6).

Moved verbatim out of TicketTab (bug-144's fix) so KBTab gets the same
freeze-proof behavior instead of its own laggy per-line insertText path.

Design note (bug-144): a fast-emitting run (many workers/tickets) can emit
log lines faster than QPlainTextEdit can append+scroll one at a time, which
froze the GUI on a 30k-ticket run. emit_log() only buffers; a 250ms QTimer
drains the buffer via flush(). flush() still issues one appendHtml call PER
LINE — each call opens its own QTextBlock, so setMaximumBlockCount(max_lines)
trims per LINE (not per flush) — but the whole loop is wrapped in
setUpdatesEnabled(False)/True so a flush costs a single repaint instead of
one repaint+scroll per line. (A prior version joined a whole flush into one
"<br>"-separated appendHtml call, which put the entire flush in one block —
max_lines then capped FLUSHES, not lines; per-line appendHtml restores the
intended cap semantics while keeping the perf fix.)
"""
from __future__ import annotations

import html as _html
import logging
from datetime import datetime

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit

# Both tabs' log lines now forward to the same "scraper" logger. (TicketTab
# already used this logger; KBTab previously forwarded to the root logging
# module via getattr(logging, level) — unified here.)
log = logging.getLogger("scraper")

_LOG_COLORS = {"error": "#c62828", "warning": "#ef6c00", "info": "#212121"}


class LogPane(QPlainTextEdit):
    """Read-only, buffered, colorized log widget capped at max_lines LINES."""

    def __init__(self, max_lines: int = 3000, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(max_lines)
        self.setFont(QFont("Consolas", 9))

        self._buf: list[tuple[str, str, str]] = []   # (ts, level, msg)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.flush)
        self._timer.start()

    def emit_log(self, level: str, msg: str):
        """Buffer only — the GUI append is deferred to the timer-driven flush()
        (bug-144: a big run emits log lines faster than QPlainTextEdit can
        append+scroll one-by-one)."""
        self._buf.append((datetime.now().strftime("%H:%M:%S"), level, msg))
        getattr(log, level if level in ("debug", "info", "warning", "error") else "info")(msg)

    def flush(self):
        if not self._buf:
            return
        buf, self._buf = self._buf, []
        self.setUpdatesEnabled(False)
        try:
            for ts_str, level, msg in buf:
                color = _LOG_COLORS.get(level, "#616161")
                # HTML collapses whitespace, so plain padding spaces would not
                # keep the level column aligned — use &nbsp; to preserve it.
                level_str = f"{level.upper():7s}".replace(" ", "&nbsp;")
                self.appendHtml(
                    f'<span style="color:{color}">'
                    f'{ts_str} {level_str} {_html.escape(msg)}</span>'
                )
        finally:
            self.setUpdatesEnabled(True)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
