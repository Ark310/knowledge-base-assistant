# tests/test_ticket_engine.py
import sys
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
