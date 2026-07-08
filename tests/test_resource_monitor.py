"""ResourceMonitorWidget — renders sampler data + pace/ETA. Offscreen Qt.

Follows the offscreen-Qt setup used by tests/test_ticket_tab.py: set
QT_QPA_PLATFORM before importing PySide6, and create the QApplication once at
module import time (no pytest fixture needed for it).
"""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

from scraper.resmon import ResourceSnapshot
from scraper.resource_monitor import ResourceMonitorWidget


class _FakeSampler:
    def sample(self):
        return ResourceSnapshot(cpu_pct=55.0, ram_total_mb=16000, ram_used_mb=9000,
                                 ram_free_mb=7000, app_rss_mb=250,
                                 chrome_procs=[(11, 400), (12, 300)], chrome_total_mb=700)


def test_refresh_renders_sampler_values():
    w = ResourceMonitorWidget(sampler=_FakeSampler())
    w.refresh_now()
    txt = w.lbl_system.text() + w.lbl_chrome.text()
    assert "55" in txt and "7000" in txt.replace(",", "") or "7,000" in txt
    assert "2 proc" in w.lbl_chrome.text()


def test_pace_and_eta_from_progress():
    w = ResourceMonitorWidget(sampler=_FakeSampler())
    w._clock = iter([0.0, 60.0]).__next__          # two ticks, 60s apart
    w.set_progress(0, 1000)
    w.set_progress(60, 1000)                        # 60 tickets/min
    assert "60" in w.lbl_pace.text()                # pace shown
    assert "15m" in w.lbl_pace.text() or "0h 15m" in w.lbl_pace.text()   # 940/60 ≈ 15.7m


def test_no_sampler_renders_dashes():
    w = ResourceMonitorWidget(sampler=None)
    w.refresh_now()
    assert "—" in w.lbl_system.text()
