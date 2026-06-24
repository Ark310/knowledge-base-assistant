# tests/test_ticket_engine.py
import sys
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.control import RunControl
from scraper import ticket_engine as te

FIX = Path(__file__).parent / "fixtures" / "tradedesk"
def fx(n): return (FIX / n).read_text(encoding="utf-8")

class FakeBrowser:
    def close(self): pass

class FakePortal:
    """Returns Phase-1 fixtures; 'download_all' writes stub files for any 'Files N>0' ticket."""
    def __init__(self, portal_url, found=True):
        self.base = portal_url.rstrip("/"); self.b = FakeBrowser(); self.found = found
        self.logged_in = False
    def login(self, u, p): self.logged_in = True; return True
    def is_login_page(self, html): return False
    def ticket_url(self, tid): return f"{self.base}/tickets/{tid}/edit"
    def open_ticket(self, tid):
        return fx("ticket_detail.html") if self.found else fx("not_found.html")
    def subview_count(self, label):
        return {"resolve": 1, "files": 2}.get(label.lower(), 0)
    def open_subview(self, label, ready_selector=None):
        return fx("resolution.html") if label.lower().startswith("resolve") else fx("files.html")
    def download_all(self, dest_dir):
        dest_dir = Path(dest_dir); dest_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for name in ("error-log.txt", "resolution-script.sql"):
            p = dest_dir / name; p.write_text("stub"); out.append(p)
        return out

def _cb(rec):
    return te.TicketEngineCallbacks(
        on_log=lambda l, m: None,
        on_progress=lambda i, n: rec.setdefault("progress", []).append((i, n)),
        on_ticket=lambda tid, st: rec.setdefault("tickets", []).append((tid, st)),
        on_ticket_meta=lambda tid, title, nfiles: rec.setdefault("meta", []).append((tid, title, nfiles)),
        on_finished=lambda rep: rec.update(report=rep),
    )

def test_workers_clamped_to_10():
    assert te._clamp_workers(99) == 10 and te._clamp_workers(0) == 1 and te._clamp_workers(4) == 4

def test_scrapes_ticket_with_resolution_and_files(tmp_path):
    rec = {}
    te.run_ticket_scrape("https://portal.contoso.example", "u", "p", ["76511"],
                         force=True, cb=_cb(rec), workers=1, output_dir=tmp_path,
                         portal_factory=lambda url: FakePortal(url))
    assert (tmp_path / "ticket_76511.json").exists()
    import json
    d = json.loads((tmp_path / "ticket_76511.json").read_text(encoding="utf-8"))
    assert d["resolution"]["text"]
    assert len(d["attachments"]) == 2
    assert rec["report"]["saved"] == 1
    assert ("76511", "ok") in rec["tickets"]
    assert rec["meta"] and rec["meta"][0][0] == "76511" and rec["meta"][0][2] == 2  # files count

def test_not_found_reported(tmp_path):
    rec = {}
    te.run_ticket_scrape("https://portal.contoso.example", "u", "p", ["999"],
                         force=True, cb=_cb(rec), workers=1, output_dir=tmp_path,
                         portal_factory=lambda url: FakePortal(url, found=False))
    assert rec["report"]["not_found"] == 1
    assert not (tmp_path / "ticket_999.json").exists()

def test_cancel_before_run_scrapes_nothing(tmp_path):
    rec = {}; ctrl = RunControl(); ctrl.cancel()
    te.run_ticket_scrape("https://portal.contoso.example", "u", "p", ["76511"],
                         force=True, cb=_cb(rec), workers=1, output_dir=tmp_path, control=ctrl,
                         portal_factory=lambda url: FakePortal(url))
    assert rec["report"]["saved"] == 0

def test_cancellationtoken_alias_is_runcontrol():
    assert te.CancellationToken is RunControl

def test_cancel_during_run_stops_early(tmp_path):
    ctrl = RunControl()

    class CancelOnFirstPortal(FakePortal):
        """Cancels the shared RunControl on the first open_ticket call."""
        def __init__(self, url):
            super().__init__(url)
            self._first = True
        def open_ticket(self, tid):
            if self._first:
                self._first = False
                ctrl.cancel()
            return fx("ticket_detail.html")

    rec = {}
    te.run_ticket_scrape("https://portal.contoso.example", "u", "p", ["76511", "76512"],
                         force=True, cb=_cb(rec), workers=1, output_dir=tmp_path,
                         control=ctrl, portal_factory=lambda url: CancelOnFirstPortal(url))
    # Ticket 1 completes (cancel fires during its fetch, not before).
    # Ticket 2's top-of-loop cancelled check breaks before any fetch.
    assert rec["report"]["saved"] == 1
    assert (tmp_path / "ticket_76511.json").exists()
    assert not (tmp_path / "ticket_76512.json").exists()

def test_legacy_cancel_kwarg_path(tmp_path):
    ctrl = RunControl(); ctrl.cancel()
    rec = {}
    te.run_ticket_scrape("https://portal.contoso.example", "u", "p", ["76511"],
                         force=True, cb=_cb(rec), workers=1, output_dir=tmp_path,
                         cancel=ctrl,  # legacy kwarg, NOT control=
                         portal_factory=lambda url: FakePortal(url))
    assert rec["report"]["saved"] == 0


# ── Worker-crash resilience (robust redispatch / no stranded "queued" tickets) ──

def _crashing_factory(crash_rule, lock=None):
    """portal_factory whose open_ticket raises per `crash_rule(tid, prior_crashes)`.

    crash_rule receives (tid, n_prior_crashes_for_tid) and returns True to crash.
    Crash counts are shared across rebuilt portals and all workers.
    """
    lock = lock or threading.Lock()
    crashes: dict[str, int] = {}

    def factory(url):
        p = FakePortal(url)
        def open_ticket(tid):
            with lock:
                n = crashes.get(tid, 0)
            if crash_rule(tid, n):
                with lock:
                    crashes[tid] = n + 1
                raise RuntimeError("simulated tab crash")
            return fx("ticket_detail.html")
        p.open_ticket = open_ticket
        return p
    return factory, crashes


def test_transient_worker_crash_is_redispatched_then_succeeds(tmp_path):
    # 76511 crashes once, then succeeds on retry; 76512 is fine throughout.
    factory, crashes = _crashing_factory(
        lambda tid, n: tid == "76511" and n == 0)
    rec = {}
    rep = te.run_ticket_scrape("https://portal.contoso.example", "u", "p",
                               ["76511", "76512"], force=True, cb=_cb(rec),
                               workers=1, output_dir=tmp_path, portal_factory=factory)
    statuses = dict(rec["tickets"])
    assert statuses.get("76511") == "ok"        # redispatched + retried to success
    assert statuses.get("76512") == "ok"
    assert crashes["76511"] == 1                 # crashed exactly once
    assert rep["saved"] == 2 and rep["failed"] == 0
    assert (tmp_path / "ticket_76511.json").exists()


def test_permanently_crashing_ticket_is_failed_not_stranded(tmp_path):
    # "BAD" always crashes; the two good tickets must still complete, and BAD must
    # reach a terminal "failed" (bounded retries) — never left in "queued".
    factory, crashes = _crashing_factory(lambda tid, n: tid == "BAD")
    rec = {}
    rep = te.run_ticket_scrape("https://portal.contoso.example", "u", "p",
                               ["76511", "BAD", "76512"], force=True, cb=_cb(rec),
                               workers=1, output_dir=tmp_path, portal_factory=factory)
    statuses = dict(rec["tickets"])
    assert statuses["76511"] == "ok"
    assert statuses["76512"] == "ok"
    assert statuses["BAD"] == "failed"
    assert len(rec["tickets"]) == 3              # every ticket got exactly one terminal status
    assert crashes["BAD"] == te.MAX_TICKET_ATTEMPTS
    assert rep["saved"] == 2 and rep["failed"] == 1


def test_all_workers_die_remaining_tickets_marked_failed(tmp_path):
    # Every open_ticket crashes -> the worker exhausts its rebuild budget and exits;
    # the safety-net drain must mark ALL tickets failed (none left "queued").
    factory, _ = _crashing_factory(lambda tid, n: True)
    rec = {}
    ids = ["1", "2", "3", "4", "5"]
    rep = te.run_ticket_scrape("https://portal.contoso.example", "u", "p", ids,
                               force=True, cb=_cb(rec), workers=1,
                               output_dir=tmp_path, portal_factory=factory)
    statuses = dict(rec["tickets"])
    assert all(statuses.get(t) == "failed" for t in ids)
    assert len(rec["tickets"]) == len(ids)       # exactly one terminal status per ticket
    assert rep["failed"] == len(ids) and rep["saved"] == 0
    assert rep["retried"] == 0


def test_multi_worker_crash_is_redispatched_under_concurrency(tmp_path):
    # 3 workers, 6 tickets; "A3" crashes once (whichever worker pulls it first) then
    # succeeds on redispatch. The shared queue means another worker finishes it — under
    # concurrency every ticket still reaches exactly one terminal "ok", none stranded.
    factory, crashes = _crashing_factory(lambda tid, n: tid == "A3" and n == 0)
    rec = {}
    ids = ["A1", "A2", "A3", "A4", "A5", "A6"]
    rep = te.run_ticket_scrape("https://portal.contoso.example", "u", "p", ids,
                               force=True, cb=_cb(rec), workers=3,
                               output_dir=tmp_path, portal_factory=factory)
    statuses = dict(rec["tickets"])
    assert set(statuses) == set(ids)
    assert all(v == "ok" for v in statuses.values())
    assert crashes["A3"] == 1                     # crashed once, redispatched, then ok
    assert len(rec["tickets"]) == len(ids)        # finished-guard holds: one terminal per ticket
    assert rep["saved"] == 6 and rep["failed"] == 0
    assert rep["retried"] == 1                     # exactly the one redispatched ticket
