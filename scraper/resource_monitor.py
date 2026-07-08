"""Resource monitor panel (v4.0.3, R5): system CPU/RAM, app RAM, Chrome process
rollup, pace + ETA. Pure display — sampling comes from resmon.ResourceSampler;
pace comes from on_progress events. QTimer keeps refresh on the GUI thread.

Never lets a sampling failure take down a run: refresh_now() swallows any
exception from the sampler (resmon.ResourceSampler already swallows its own
per-process failures; this is belt-and-suspenders for a totally dead sampler).
"""
from __future__ import annotations
import logging
import time
from collections import deque

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGroupBox, QGridLayout, QLabel

log = logging.getLogger("scraper")


def _fmt_eta(minutes: float) -> str:
    if minutes <= 0 or minutes != minutes:      # NaN guard
        return "—"
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


class ResourceMonitorWidget(QGroupBox):
    def __init__(self, sampler=None, parent=None):
        super().__init__("Resources & Speed", parent)
        self._sampler = sampler
        self._clock = time.monotonic
        self._points: deque[tuple[float, int]] = deque(maxlen=90)   # (t, done) ~3min
        self._total = 0
        g = QGridLayout(self)
        g.setContentsMargins(10, 6, 10, 6)
        self.lbl_system = QLabel("CPU — · RAM —")
        self.lbl_app = QLabel("App —")
        self.lbl_chrome = QLabel("Chrome —")
        self.lbl_workers = QLabel("Workers —")
        self.lbl_pace = QLabel("Pace — · ETA —")
        for i, w in enumerate((self.lbl_system, self.lbl_app, self.lbl_chrome,
                               self.lbl_workers, self.lbl_pace)):
            g.addWidget(w, i // 3, i % 3)
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.refresh_now)

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def set_workers_info(self, active: int):
        self.lbl_workers.setText(f"Workers {active}")

    def set_progress(self, current: int, total: int):
        self._total = total
        self._points.append((self._clock(), current))
        if len(self._points) >= 2:
            (t0, c0), (t1, c1) = self._points[0], self._points[-1]
            if t1 > t0 and c1 > c0:
                per_min = (c1 - c0) / (t1 - t0) * 60.0
                remaining = max(0, total - c1)
                self.lbl_pace.setText(
                    f"Pace {per_min:.0f}/min · ETA {_fmt_eta(remaining / per_min)}")

    def reset_run(self):
        self._points.clear()
        self.lbl_pace.setText("Pace — · ETA —")

    def refresh_now(self):
        if self._sampler is None:
            self.lbl_system.setText("CPU — · RAM —")
            return
        try:
            s = self._sampler.sample()
        except Exception as exc:
            log.debug("resource_monitor: sample failed (%s)", type(exc).__name__)
            return
        self.lbl_system.setText(
            f"CPU {s.cpu_pct:.0f}% · RAM {s.ram_used_mb:,}/{s.ram_total_mb:,} MB "
            f"(free {s.ram_free_mb:,})")
        self.lbl_app.setText(f"App {s.app_rss_mb:,} MB")
        self.lbl_chrome.setText(
            f"Chrome {len(s.chrome_procs)} proc · {s.chrome_total_mb:,} MB")
        self.lbl_chrome.setToolTip("\n".join(
            f"PID {pid}: {mb:,} MB" for pid, mb in s.chrome_procs) or "no Chrome processes")
