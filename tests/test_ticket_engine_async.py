import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.control import RunControl
from scraper import ticket_engine as te          # for callbacks + constants
from scraper import ticket_engine_async as tea
from scraper.portal.base_portal import empty_ticket

class FakeAsyncBrowser:
    def __init__(self): self.pages = 0
    async def open(self): return self
    async def new_page(self):
        self.pages += 1
        return object()      # opaque page handle; the fake portal ignores it
    async def close(self): pass

def _cb(rec):
    return te.TicketEngineCallbacks(
        on_log=lambda l, m: None,
        on_progress=lambda i, n: None,
        on_ticket=lambda tid, st: rec.setdefault("tickets", []).append((tid, st)),
        on_ticket_meta=lambda tid, t, n: rec.setdefault("meta", []).append((tid, t, n)),
        on_finished=lambda rep: rec.update(report=rep),
    )

def make_factory(crash_rule):
    """crash_rule(tid, prior_crashes)->bool. Shared crash counts across rebuilt portals."""
    crashes = {}
    class FakePortal:
        base = "https://x"
        def __init__(self, page): self.page = page
        def ticket_url(self, tid): return f"{self.base}/tickets/{tid}/edit"
        def is_login_page(self, html): return False
        def is_not_found(self, html, tid): return tid == "404"
        async def login(self, u, p): return True
        async def open_ticket(self, tid):
            n = crashes.get(tid, 0)
            if crash_rule(tid, n):
                crashes[tid] = n + 1
                raise RuntimeError("simulated tab crash")
            return f"<html>{tid}</html>"
        async def subview_count(self, label): return 0
        async def open_subview(self, label, ready_selector=None): return ""
        async def download_all(self, dest): return []
    return (lambda page: FakePortal(page)), crashes

def run(ids, workers, crash_rule, tmp_path, force=True, monkeyparse=True):
    rec = {}
    factory, crashes = make_factory(crash_rule)
    async def login_once(browser, u, p): return True
    # parse returns a minimal canonical ticket so save_ticket writes a file
    def fake_parse(html, tid, base):
        return None if "404" in html else {**empty_ticket(tid, f"{base}/{tid}"), "title": f"T{tid}"}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ids, force=force, control=RunControl(), cb=_cb(rec),
        workers=workers, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=factory, login_once=login_once, parse_fn=fake_parse, mode="light"))
    return rec, crashes

def test_all_tickets_reach_terminal_ok(tmp_path):
    rec, _ = run(["1", "2", "3"], 2, lambda tid, n: False, tmp_path)
    assert {t for t, _ in rec["tickets"]} == {"1", "2", "3"}
    assert all(st == "ok" for _, st in rec["tickets"])
    assert rec["report"]["saved"] == 3

def test_transient_crash_redispatched_then_ok(tmp_path):
    rec, crashes = run(["1", "2"], 2, lambda tid, n: tid == "1" and n == 0, tmp_path)
    assert dict(rec["tickets"])["1"] == "ok"
    assert crashes["1"] == 1

def test_permanent_crash_failed_not_stranded(tmp_path):
    rec, crashes = run(["1", "BAD", "2"], 2, lambda tid, n: tid == "BAD", tmp_path)
    s = dict(rec["tickets"])
    assert s["1"] == "ok" and s["2"] == "ok" and s["BAD"] == "failed"
    assert len(rec["tickets"]) == 3
    assert crashes["BAD"] == te.MAX_TICKET_ATTEMPTS

def test_all_workers_die_drains_to_failed(tmp_path):
    rec, _ = run(["1", "2", "3"], 2, lambda tid, n: True, tmp_path)
    assert all(st == "failed" for _, st in rec["tickets"])
    assert len(rec["tickets"]) == 3

def test_login_failure_drains_all_failed(tmp_path):
    # login_once returns False -> every ticket gets a terminal "failed" (never stranded).
    rec = {}
    factory, _ = make_factory(lambda tid, n: False)
    async def login_fail(browser, u, p): return False
    def fake_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ["1", "2"], force=True, control=RunControl(), cb=_cb(rec),
        workers=2, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=factory, login_once=login_fail, parse_fn=fake_parse, mode="light"))
    assert all(st == "failed" for _, st in rec["tickets"])
    assert rec["report"]["failed"] == 2 and rec["report"]["saved"] == 0

def test_cancel_before_run_skips_drain(tmp_path):
    # Pre-cancelled: workers break at the top; the leftover-drain is SKIPPED on cancel,
    # so nothing is force-marked failed (the user stopped intentionally).
    rec = {}
    ctrl = RunControl(); ctrl.cancel()
    factory, _ = make_factory(lambda tid, n: False)
    async def login_once(browser, u, p): return True
    def fake_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ["1", "2"], force=True, control=ctrl, cb=_cb(rec),
        workers=2, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=factory, login_once=login_once, parse_fn=fake_parse, mode="light"))
    assert rec.get("tickets", []) == []
    assert rec["report"]["saved"] == 0 and rec["report"]["failed"] == 0

def test_multi_mode_own_browser_and_login_per_worker(tmp_path):
    created = {"n": 0}
    def bf():
        created["n"] += 1
        return FakeAsyncBrowser()
    logins = {"n": 0}
    async def login_once(browser, u, p):
        logins["n"] += 1; return True
    factory, _ = make_factory(lambda tid, n: False)
    def fake_parse(html, tid, base):
        return {**empty_ticket(tid, base), "title": tid}
    rec = {}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ["1", "2", "3", "4"], force=True, control=RunControl(), cb=_cb(rec),
        workers=2, output_dir=tmp_path, browser_factory=bf,
        page_portal_factory=factory, login_once=login_once, parse_fn=fake_parse, mode="multi"))
    assert all(s == "ok" for _, s in rec["tickets"]) and rec["report"]["saved"] == 4
    # multi: one browser + one login PER WORKER (n_workers = min(2,4) = 2), not a single shared one
    assert created["n"] >= 2 and logins["n"] >= 2

def test_multi_mode_login_failure_drains_all_failed(tmp_path):
    async def login_fail(browser, u, p): return False
    factory, _ = make_factory(lambda tid, n: False)
    def fake_parse(html, tid, base):
        return {**empty_ticket(tid, base), "title": tid}
    rec = {}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ["1", "2"], force=True, control=RunControl(), cb=_cb(rec),
        workers=2, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=factory, login_once=login_fail, parse_fn=fake_parse, mode="multi"))
    assert all(s == "failed" for _, s in rec["tickets"]) and rec["report"]["failed"] == 2

def test_multi_mode_new_page_failure_closes_browser_no_orphan(tmp_path):
    # If new_page() fails AFTER a successful login, the just-opened browser must be
    # closed (no orphan) and the ticket must reach a terminal "failed" (not stranded).
    closed = []
    class _FailNewPageBrowser:
        async def open(self): return self
        async def new_page(self): raise RuntimeError("new_page boom")
        async def close(self): closed.append(True)
    async def login_once(browser, u, p): return True
    factory, _ = make_factory(lambda tid, n: False)
    def fake_parse(html, tid, base):
        return {**empty_ticket(tid, base), "title": tid}
    rec = {}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ["1"], force=True, control=RunControl(), cb=_cb(rec),
        workers=1, output_dir=tmp_path, browser_factory=lambda: _FailNewPageBrowser(),
        page_portal_factory=factory, login_once=login_once, parse_fn=fake_parse, mode="multi"))
    assert dict(rec["tickets"]).get("1") == "failed"   # drained, not stranded
    assert closed, "browser must be closed when new_page fails post-login (no orphan)"

def test_resolution_parser_is_injectable(tmp_path):
    seen = {}
    class ResPortal:
        base = "https://x"
        def __init__(self, page): self.page = page
        def ticket_url(self, t): return f"{self.base}/{t}"
        def is_login_page(self, h): return False
        def is_not_found(self, h, t): return False
        async def login(self, u, p): return True
        async def open_ticket(self, t): return f"<html>{t}</html>"
        async def subview_count(self, label): return 1 if label == "Resolve" else 0
        async def open_subview(self, label, ready_selector=None): return "RESHTML"
        async def download_all(self, dest): return []
    def my_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}
    def my_res(html): seen["html"] = html; return {"text": "R", "comments": [], "attachments": []}
    rec = {}
    async def login_ok(b, u, p): return True
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ["7"], force=True, control=RunControl(), cb=_cb(rec),
        workers=1, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=lambda page: ResPortal(page),
        login_once=login_ok, parse_fn=my_parse, parse_resolution_fn=my_res, mode="light"))
    assert seen.get("html") == "RESHTML"          # injected resolution parser was used
    assert dict(rec["tickets"])["7"] == "ok"
