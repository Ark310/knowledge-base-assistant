import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer
from scraper.control import RunControl
from scraper.portal.base_portal import empty_ticket
from scraper.async_runner import AsyncTicketWorker

class _FakeBrowser:
    base = "https://x"
    async def open(self): return self
    async def new_page(self): return object()
    async def close(self): pass

def _fake_ppf(page):
    class P:
        base = "https://x"
        def ticket_url(self, tid): return f"{self.base}/{tid}"
        def is_login_page(self, h): return False
        def is_not_found(self, h, tid): return False
        async def login(self, u, p): return True
        async def open_ticket(self, tid): return f"<html>{tid}</html>"
        async def subview_count(self, l): return 0
        async def open_subview(self, l, ready_selector=None): return ""
        async def download_all(self, d): return []
    return P()

async def _login_ok(browser, u, p): return True
def _fake_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}

def test_worker_emits_finished(tmp_path):
    app = QApplication.instance() or QApplication([])
    w = AsyncTicketWorker("https://x", "u", "p", ["1", "2"], force=True, workers=2,
                          output_dir=tmp_path, control=RunControl(),
                          browser_factory=lambda: _FakeBrowser(),
                          page_portal_factory=_fake_ppf, login_once=_login_ok, parse_fn=_fake_parse)
    got = {}
    loop = QEventLoop()
    w.finished_report.connect(lambda rep: (got.update(rep), loop.quit()))
    QTimer.singleShot(10_000, loop.quit)
    w.start(); loop.exec(); w.wait(2000)
    assert got.get("saved") == 2
