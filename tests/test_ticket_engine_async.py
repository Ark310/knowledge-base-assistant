import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
from scraper.control import RunControl
from scraper import ticket_engine as te          # for callbacks + constants
from scraper import ticket_engine_async as tea
from scraper.portal.base_portal import empty_ticket
from scraper.scrape_state import ScrapedState


@pytest.fixture(autouse=True)
def _isolate_scraped_state(tmp_path, monkeypatch):
    """The async engine now persists via ScrapedState() (journal + compacted JSON).
    Point every test's state at tmp_path so the suite never touches the operator's
    real scraper/state/scraped_tickets.json (v4.0.3 Task 4)."""
    monkeypatch.setattr(
        tea, "ScrapedState",
        lambda *a, **kw: ScrapedState(state_file=tmp_path / "scraped_tickets.json", **kw))


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

def test_persistent_crashes_fail_tickets_not_stranded(tmp_path):
    # v4.0.3: workers no longer die on repeated crashes in light mode (they recover in
    # place — bug-116); every persistently-crashing ticket still reaches a terminal
    # "failed" via MAX_TICKET_ATTEMPTS, never stranded at "queued".
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

def test_worker_survives_interspersed_failures(tmp_path):
    # bug-111: `rebuilds` was a LIFETIME counter (never reset on success), so a single
    # worker accumulating > MAX_WORKER_REBUILDS transient failures across a long batch
    # would exit even with many successes between them — collapsing the pool on big
    # runs. With a CONSECUTIVE budget (reset on each success), one transient failure on
    # each even ticket must NOT kill the worker: all 10 tickets complete.
    ids = [str(i) for i in range(1, 11)]            # 1..10  -> 5 evens fail once each
    rec, _ = run(ids, 1, lambda tid, n: int(tid) % 2 == 0 and n == 0, tmp_path)
    s = dict(rec["tickets"])
    assert all(s.get(t) == "ok" for t in ids), f"some tickets did not complete: {s}"
    assert rec["report"]["saved"] == 10


def test_large_drain_is_capped_no_ui_flood(tmp_path):
    # bug-111: a mass drain with hundreds/thousands of pending tickets must NOT emit
    # one GUI update per ticket (that flooded the Qt queue and hung the app on the 18k
    # run). Since v4.0.3 an INFRA failure never drains (the run pauses — bug-116), so
    # the remaining mass-drain path is startup LOGIN failure: all 300 pending tickets
    # are accounted failed, but per-ticket on_ticket emits stay capped.
    ids = [str(i) for i in range(1, 301)]                 # 300 tickets
    rec = {}
    factory, _ = make_factory(lambda tid, n: False)
    async def login_fail(browser, u, p): return False
    def fake_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ids, force=True, control=RunControl(), cb=_cb(rec),
        workers=1, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=factory, login_once=login_fail, parse_fn=fake_parse, mode="light"))
    assert rec["report"]["failed"] == 300                 # all accounted as failed
    assert len(rec.get("tickets", [])) <= tea._DRAIN_TICKET_CAP   # NOT 300 — capped


def test_page_recycled_on_long_run(tmp_path, monkeypatch):
    # bug-111 endurance: a worker reopens a fresh tab every PAGE_RECYCLE_EVERY successful
    # tickets to shed per-tab memory. With the interval at 3, a 7-ticket run recycles
    # twice -> the shared browser hands out > 1 page (initial + 2 recycles).
    monkeypatch.setattr(tea, "PAGE_RECYCLE_EVERY", 3)
    browser = FakeAsyncBrowser()
    factory, _ = make_factory(lambda tid, n: False)        # never crash
    async def login_once(b, u, p): return True
    def fake_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}
    rec = {}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", [str(i) for i in range(1, 8)],
        force=True, control=RunControl(), cb=_cb(rec),
        workers=1, output_dir=tmp_path, browser_factory=lambda: browser,
        page_portal_factory=factory, login_once=login_once, parse_fn=fake_parse, mode="light"))
    assert rec["report"]["saved"] == 7
    assert browser.pages >= 3, "page should have been recycled at least twice"


def test_circuit_breaker_pauses_on_sustained_failure(tmp_path, monkeypatch):
    # bug-111: when failures persist after throttling to the floor, the run PAUSES for
    # operator attention instead of mass-failing. Use a small window so the breaker trips
    # quickly, and a control whose pause() also cancels so the test can never hang.
    import scraper.throttle as throttle
    monkeypatch.setattr(tea, "AdaptiveGate",
        lambda mp: throttle.AdaptiveGate(mp, window=6, min_permits=1, breaker_at=0.85,
                                         backoff_base=0.01, backoff_max=0.05))
    paused = {"n": 0}
    class Ctl(RunControl):
        def pause(self):
            paused["n"] += 1
            self.cancel()                                  # break workers out -> no hang
    factory, _ = make_factory(lambda tid, n: True)         # everything fails
    async def login_once(b, u, p): return True
    def fake_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}
    rec = {}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", [str(i) for i in range(1, 41)],
        force=True, control=Ctl(), cb=_cb(rec),
        workers=4, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=factory, login_once=login_once, parse_fn=fake_parse, mode="light"))
    assert paused["n"] >= 1, "breaker should pause the run on sustained failure"


def test_shared_browser_death_recovers_and_never_mass_fails(tmp_path, monkeypatch):
    # bug-116 regression (2026-07-02: 28,620 tickets mass-failed): the ONE shared
    # Chrome dies mid-run. The worker's tab rebuild fails on the corpse, which must
    # trigger single-flight BrowserSupervisor recovery (new browser + re-login) —
    # the run then COMPLETES: zero failed, all saved, one recovery log line.
    import scraper.throttle as throttle
    monkeypatch.setattr(tea, "_RECOVER_RETRY_DELAY", 0.01)
    monkeypatch.setattr(tea, "AdaptiveGate",
        lambda mp: throttle.AdaptiveGate(mp, backoff_base=0.01, backoff_max=0.02))

    class DyingBrowser:
        """Hands out die_after pages, then every new_page raises (Chrome corpse)."""
        def __init__(self, die_after):
            self.die_after = die_after; self.pages = 0; self.closed = False
        async def open(self): return self
        async def new_page(self):
            self.pages += 1
            if self.pages > self.die_after:
                raise RuntimeError("chrome dead")
            return object()
        async def close(self): self.closed = True

    browsers = []
    def bf():
        # 1st browser serves the 2 initial worker tabs, then is a corpse; the
        # factory's NEXT browser (post-recovery) is healthy.
        b = DyingBrowser(2) if not browsers else FakeAsyncBrowser()
        browsers.append(b)
        return b

    factory, _ = make_factory(lambda tid, n: tid == "3" and n == 0)  # one tab crash
    async def login_once(b, u, p): return True
    def fake_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}
    logs = []
    rec = {}
    cb = _cb(rec)
    cb.on_log = lambda lvl, msg: logs.append(msg)
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", [str(i) for i in range(1, 7)],
        force=True, control=RunControl(), cb=cb,
        workers=2, output_dir=tmp_path, browser_factory=bf,
        page_portal_factory=factory, login_once=login_once, parse_fn=fake_parse, mode="light"))
    assert rec["report"]["failed"] == 0, f"mass-fail regression: {rec['report']}"
    assert rec["report"]["saved"] == 6
    assert any("shared browser recovered" in m for m in logs)
    assert len(browsers) == 2 and browsers[0].closed is True


def test_supervisor_give_up_pauses_and_alerts_instead_of_draining(tmp_path, monkeypatch):
    # bug-116: when the browser is UNRECOVERABLE (factory keeps failing), the engine
    # must PAUSE with exactly ONE alert and keep every pending ticket queued (zero
    # drained/failed) — the operator's Stop (cancel) then releases the run cleanly.
    monkeypatch.setattr(tea, "_RECOVER_RETRY_DELAY", 0.01)

    class NewPageDead:
        """Opens + logs in fine, but every new_page raises (dies right away)."""
        def __init__(self): self.closed = False
        async def open(self): return self
        async def new_page(self): raise RuntimeError("chrome dead")
        async def close(self): self.closed = True

    class DeadOnArrival:
        async def open(self): raise RuntimeError("no chrome")
        async def close(self): pass

    browsers = []
    def bf():
        b = NewPageDead() if not browsers else DeadOnArrival()
        browsers.append(b)
        return b

    factory, _ = make_factory(lambda tid, n: False)
    async def login_once(b, u, p): return True
    def fake_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}
    alerts = []
    rec = {}
    cb = _cb(rec)
    cb.on_alert = lambda s, t, b: alerts.append((s, t, b))
    ctrl = RunControl()

    async def main():
        task = asyncio.create_task(tea.run_ticket_scrape_async(
            "https://x", "u", "p", ["1", "2", "3", "4"],
            force=True, control=ctrl, cb=cb,
            workers=2, output_dir=tmp_path, browser_factory=bf,
            page_portal_factory=factory, login_once=login_once,
            parse_fn=fake_parse, mode="light"))
        for _ in range(500):                    # wait (≤5 s) for the give-up pause
            if ctrl.paused:
                break
            await asyncio.sleep(0.01)
        assert ctrl.paused, "engine must pause when the browser is unrecoverable"
        ctrl.cancel()                            # operator presses Stop
        return await asyncio.wait_for(task, timeout=10)

    stats = asyncio.run(main())
    assert len(alerts) == 1, f"exactly ONE alert expected, got {alerts}"
    assert alerts[0][0] == "error"
    assert stats["failed"] == 0 and stats["saved"] == 0   # nothing drained/failed
    assert rec.get("tickets", []) == []                   # no per-ticket emits


def test_ok_log_line_includes_comment_and_file_counts(tmp_path):
    # R1: per-ticket [OK] line reports the main-thread comment count like the
    # resolution line does (bug-117 operator ask: quick eyeball of how much a
    # ticket actually captured, no need to open the JSON).
    factory, _ = make_factory(lambda tid, n: False)
    async def login_once(b, u, p): return True
    def fake_parse(html, tid, base):
        return {**empty_ticket(tid, base), "title": tid,
                "comments": [{}, {}, {}]}
    logs = []
    rec = {}
    cb = _cb(rec)
    cb.on_log = lambda lvl, msg: logs.append(msg)
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ["1"], force=True, control=RunControl(), cb=cb,
        workers=1, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=factory, login_once=login_once, parse_fn=fake_parse, mode="light"))
    assert dict(rec["tickets"])["1"] == "ok"
    ok_lines = [m for m in logs if "[OK] #1" in m]
    assert ok_lines, f"no [OK] line found in logs: {logs}"
    assert "3 comment(s)/email(s)" in ok_lines[0], ok_lines[0]
    assert "0 file(s)" in ok_lines[0], ok_lines[0]


def test_workers_park_when_target_lowered(tmp_path):
    # v4.0.3 Task 7: 4 workers over a slow queue; lower control.target_workers to 1 after
    # the first ticket. The run must still complete ALL 12 tickets, and once the lowered
    # target settles only worker 0 keeps pulling — max concurrent in-flight AFTER the
    # change is 1 (surplus workers park: they hold NO page and don't pull work, then exit
    # cleanly when the queue drains). Concurrency is tracked inside the fake portal.
    control = RunControl()
    ids = [str(i) for i in range(1, 13)]
    state = {"inflight": 0, "max_after": 0, "measure": False, "completed": 0}

    class SlowPortal:
        base = "https://x"
        def __init__(self, page): self.page = page
        def ticket_url(self, t): return f"{self.base}/{t}"
        def is_login_page(self, h): return False
        def is_not_found(self, h, t): return False
        async def login(self, u, p): return True
        async def open_ticket(self, t):
            state["inflight"] += 1
            if state["measure"]:
                state["max_after"] = max(state["max_after"], state["inflight"])
            try:
                await asyncio.sleep(0.03)                  # slow queue
                return f"<html>{t}</html>"
            finally:
                state["inflight"] -= 1
                state["completed"] += 1
        async def subview_count(self, label): return 0
        async def open_subview(self, label, ready_selector=None): return ""
        async def download_all(self, dest): return []

    async def login_once(b, u, p): return True
    def fake_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}
    rec = {}

    async def main():
        task = asyncio.create_task(tea.run_ticket_scrape_async(
            "https://x", "u", "p", ids, force=True, control=control, cb=_cb(rec),
            workers=4, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
            page_portal_factory=lambda page: SlowPortal(page),
            login_once=login_once, parse_fn=fake_parse, mode="light"))
        while state["completed"] < 1:                     # after the first ticket
            await asyncio.sleep(0.005)
        control.target_workers = 1
        while state["inflight"] > 1:                       # let the pre-change batch drain
            await asyncio.sleep(0.005)
        state["max_after"] = 0
        state["measure"] = True                            # now measure post-change load
        await asyncio.wait_for(task, timeout=15)

    asyncio.run(main())
    assert {t for t, _ in rec["tickets"]} == set(ids)      # ALL tickets completed
    assert all(st == "ok" for _, st in rec["tickets"])
    assert rec["report"]["saved"] == 12
    assert state["max_after"] == 1, state                  # only 1 worker active after change


def test_tuner_lowers_permits_under_cpu_pressure(tmp_path, monkeypatch):
    # v4.0.3 Task 7: a ResourceSampler reporting cpu=99 must, via the periodic _tuner task,
    # drive the gate's permits BELOW its max during the run. Shrink _TUNER_INTERVAL so the
    # tuner fires many times, capture the live gate by patching AdaptiveGate, and probe
    # gate.permits from inside the fake portal (recording the minimum seen).
    import scraper.throttle as throttle
    monkeypatch.setattr(tea, "_TUNER_INTERVAL", 0.01)
    holder = {}
    def _make_gate(mp):
        g = throttle.AdaptiveGate(mp, backoff_base=0.0, backoff_max=0.0)
        holder["gate"] = g
        return g
    monkeypatch.setattr(tea, "AdaptiveGate", _make_gate)

    from scraper.resmon import ResourceSnapshot
    class FakeSampler:
        def sample(self): return ResourceSnapshot(cpu_pct=99.0, ram_free_mb=200)

    seen = {"min_permits": 10 ** 9}
    class ProbePortal:
        base = "https://x"
        def __init__(self, page): self.page = page
        def ticket_url(self, t): return f"{self.base}/{t}"
        def is_login_page(self, h): return False
        def is_not_found(self, h, t): return False
        async def login(self, u, p): return True
        async def open_ticket(self, t):
            await asyncio.sleep(0.05)                       # slow enough for the tuner to fire
            g = holder.get("gate")                          # read AFTER the wait: the tuner
            if g is not None:                               # has decremented during it, and
                seen["min_permits"] = min(seen["min_permits"], g.permits)  # release hasn't bumped yet
            return f"<html>{t}</html>"
        async def subview_count(self, label): return 0
        async def open_subview(self, label, ready_selector=None): return ""
        async def download_all(self, dest): return []

    async def login_once(b, u, p): return True
    def fake_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}
    rec = {}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", [str(i) for i in range(1, 13)],
        force=True, control=RunControl(), cb=_cb(rec),
        workers=3, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=lambda page: ProbePortal(page),
        login_once=login_once, parse_fn=fake_parse, mode="light", sampler=FakeSampler()))
    assert rec["report"]["saved"] == 12
    assert holder["gate"].max_permits == 3                 # ceiling unchanged (target=None)
    assert seen["min_permits"] < 3, seen                   # cpu=99 tuning throttled permits


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
