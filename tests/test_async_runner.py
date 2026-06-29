import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
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

def test_worker_stores_portal_kind_default():
    """AsyncTicketWorker defaults to portal_kind='tradedesk'."""
    app = QApplication.instance() or QApplication([])
    w = AsyncTicketWorker("https://x", "u", "p", ["1"],
                          browser_factory=lambda: _FakeBrowser(),
                          page_portal_factory=_fake_ppf, login_once=_login_ok,
                          parse_fn=_fake_parse)
    assert w._portal_kind == "tradedesk"


def test_worker_stores_portal_kind_contoso():
    """AsyncTicketWorker accepts portal_kind='contoso' and stores it."""
    app = QApplication.instance() or QApplication([])
    w = AsyncTicketWorker("https://x", "u", "p", ["1"],
                          browser_factory=lambda: _FakeBrowser(),
                          page_portal_factory=_fake_ppf, login_once=_login_ok,
                          parse_fn=_fake_parse, portal_kind="contoso")
    assert w._portal_kind == "contoso"


def test_contoso_wiring_selected_in_run(tmp_path, monkeypatch):
    """When portal_kind='contoso' and browser_factory=None, run() selects the contoso
    adapter: contoso_login_once and contoso's make_factory are imported and used."""
    app = QApplication.instance() or QApplication([])

    wiring_calls = {}

    # Fake contoso portal module injected via monkeypatch
    class _FakeDS:
        base = "https://support.contoso.example"
        def __init__(self, page): pass
        def ticket_url(self, tid): return f"{self.base}/{tid}"
        def is_login_page(self, h): return False
        def is_not_found(self, h, tid): return False
        async def login(self, u, p): return True
        async def open_ticket(self, tid): return f"<html>{tid}</html>"
        async def subview_count(self, l): return 0
        async def open_subview(self, l, ready_selector=None): return ""
        async def download_all(self, d): return []

    def _fake_ds_factory(url):
        wiring_calls["factory"] = url
        return lambda page: _FakeDS(page)

    async def _fake_ds_login(browser, u, p):
        wiring_calls["login"] = True
        return True

    def _fake_ds_detail(html, tid, base):
        return {**empty_ticket(tid, base), "title": tid}

    def _fake_ds_res(html):
        return {"text": "", "comments": [], "attachments": []}

    # Patch the contoso portal and parser modules before run() imports them
    import scraper.portal.contoso_portal as dp_mod
    import scraper.parsers.contoso_parser as ds_par_mod
    monkeypatch.setattr(dp_mod, "make_factory", _fake_ds_factory)
    monkeypatch.setattr(dp_mod, "contoso_login_once", _fake_ds_login)
    monkeypatch.setattr(ds_par_mod, "parse_ticket_detail", _fake_ds_detail)
    monkeypatch.setattr(ds_par_mod, "parse_resolution", _fake_ds_res)

    # Also patch AsyncBrowser so no real browser is launched
    import scraper.portal.async_browser as ab_mod

    class _FakeBrowserReal:
        base = "https://support.contoso.example"
        async def open(self): return self
        async def new_page(self): return object()
        async def close(self): pass

    monkeypatch.setattr(ab_mod, "AsyncBrowser", lambda headless=False: _FakeBrowserReal())

    w = AsyncTicketWorker("https://support.contoso.example", "u", "p", ["1"],
                          force=True, workers=1, output_dir=tmp_path,
                          control=RunControl(), portal_kind="contoso")
    got = {}
    loop = QEventLoop()
    w.finished_report.connect(lambda rep: (got.update(rep), loop.quit()))
    QTimer.singleShot(12_000, loop.quit)
    w.start(); loop.exec(); w.wait(3000)

    assert wiring_calls.get("factory") == "https://support.contoso.example", \
        "contoso make_factory was not called — wrong adapter selected"
    assert wiring_calls.get("login") is True, \
        "contoso_login_once was not called — wrong login selected"


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
