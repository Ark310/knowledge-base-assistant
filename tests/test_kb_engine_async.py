"""Async parallel KB engine tests (v4.0.4 Task 4).

Mirrors tests/test_ticket_engine_async.py's fake-browser style. The fake page
satisfies the REAL scraper.kb_page_ops.capture_article (goto / wait_for_timeout /
locator / screenshot / content), and parse_article / save_article /
generate_kb_index / audit_spaces module refs in kb_engine_async are monkeypatched
to lightweight fakes so no real files or network are touched.

bug-149 isolation: an AUTOUSE fixture points kb_engine_async.load_kb_state at a
tmp_path-backed ScrapedState AND redirects KB_REPORT_FILE into tmp_path, so a full
`pytest tests/` never mutates the operator's real scraper/state/ ledger or report.
"""
import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest

from scraper.control import RunControl
from scraper.engine import EngineCallbacks
from scraper.scrape_state import ScrapedState
from scraper.kb_state import kb_key
from scraper import kb_engine_async as kea


# ── fakes ────────────────────────────────────────────────────────────────────
class _EmptyLocator:
    async def all(self): return []          # expand_macros finds no expand buttons


class FakePage:
    """Satisfies capture_article. `cfg` is a shared dict driving crash/freeze rules."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.url = None
        self.closed = False

    async def goto(self, url, wait_until=None, timeout=None):
        self.url = url
        rule = self.cfg.get("crash_rule")
        if rule is not None:
            n = self.cfg["crashes"].get(url, 0)
            if rule(url, n):
                self.cfg["crashes"][url] = n + 1
                raise RuntimeError("simulated tab crash")

    async def wait_for_timeout(self, ms): pass
    def locator(self, sel): return _EmptyLocator()
    async def screenshot(self, path=None, full_page=None): pass

    async def content(self):
        if self.url in self.cfg.get("freeze_urls", ()):
            await asyncio.Event().wait()    # never set -> hangs until wait_for cancels
        return f"<html>{self.url}</html>"

    async def close(self): self.closed = True


class FakeBrowser:
    """Hands out FakePages. If die_after is set, new_page raises past that count
    (Chrome corpse) so the BrowserSupervisor recovery path is exercised."""
    def __init__(self, cfg, die_after=None):
        self.cfg = cfg
        self.die_after = die_after
        self.pages = 0
        self.closed = False

    async def open(self): return self

    async def new_page(self):
        self.pages += 1
        if self.die_after is not None and self.pages > self.die_after:
            raise RuntimeError("chrome dead")
        return FakePage(self.cfg)

    async def close(self): self.closed = True


class RecCB(EngineCallbacks):
    def __init__(self):
        self.logs, self.status, self.progress, self.alerts = [], [], [], []
    def on_log(self, level, msg): self.logs.append((level, msg))
    def on_status(self, sk, stats): self.status.append((sk, dict(stats)))
    def on_progress(self, sk, title, done, total): self.progress.append((sk, title, done, total))
    def on_alert(self, sev, title, body): self.alerts.append((sev, title, body))


def _space(key, product="tradedesk", lib=None):
    return {"space_key": key, "display_name": key.title(), "product": product,
            "product_label": "TradeDesk KB", "lib_folder": lib or key.lower()}


def _art(i):
    return {"title": f"Article {i}", "url": f"https://kb/a{i}", "slug": f"a{i}", "page_id": str(i)}


# ── autouse isolation (bug-149) ────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def kbenv(tmp_path, monkeypatch):
    """Redirect state + report into tmp_path and fake parse/save/index. Returns a
    harness (state, saved list, index-call counter) tests can inspect."""
    state = ScrapedState(state_file=tmp_path / "scraped_articles_v2.json")
    state.load()
    monkeypatch.setattr(kea, "load_kb_state", lambda *a, **k: state)
    monkeypatch.setattr(kea, "KB_REPORT_FILE", tmp_path / "last_kb_run_report.json")

    saved, idx_calls = [], []

    def fake_parse(html, *, space_key, space_name, product, title, url, screenshot_path):
        return {"space_key": space_key, "space_name": space_name, "product": product,
                "title": title, "url": url, "screenshot_path": screenshot_path}

    def fake_save(data, output_base, cfg):
        saved.append((cfg["space_key"], data["url"]))

    monkeypatch.setattr(kea, "parse_article", fake_parse)
    monkeypatch.setattr(kea, "save_article", fake_save)
    monkeypatch.setattr(kea, "generate_kb_index", lambda *a, **k: idx_calls.append(1))
    return {"state": state, "saved": saved, "idx_calls": idx_calls, "tmp": tmp_path}


def _run(space_cfgs, *, cfg_state, workers=3, force=True, control=None, cb=None,
         items=None, discover=None, run_audit=False, die_after=None, sampler=None):
    """Drive the engine with a FakeBrowser factory. `cfg_state` is the shared
    crash/freeze dict passed to every FakePage."""
    control = control or RunControl()
    cb = cb or RecCB()
    browsers = []
    def bf():
        b = (FakeBrowser(cfg_state, die_after=die_after) if not browsers
             else FakeBrowser(cfg_state))     # post-recovery browser is healthy
        browsers.append(b)
        return b
    report = asyncio.run(kea.run_kb_scrape_async(
        space_cfgs, force=force, control=control, cb=cb, workers=workers,
        output_base=cfg_state["tmp"], browser_factory=bf, items=items,
        discover=discover, run_audit=run_audit, sampler=sampler))
    return report, cb, browsers


# ── tests ──────────────────────────────────────────────────────────────────────
def test_parallel_scrape_all_articles_saved(kbenv):
    cfg_state = {"tmp": kbenv["tmp"]}
    A, B = _space("SpaceA", lib="a"), _space("SpaceB", lib="b")
    arts = {"SpaceA": [_art(i) for i in range(1, 5)], "SpaceB": [_art(i) for i in range(5, 9)]}
    discover = lambda sk: arts[sk]
    report, cb, _ = _run([A, B], cfg_state=cfg_state, workers=3, discover=discover)

    assert report["spaces"]["SpaceA"]["new"] == 4
    assert report["spaces"]["SpaceB"]["new"] == 4
    assert report["spaces"]["SpaceA"]["discovered"] == 4
    assert report["totals"]["new"] == 8 and report["totals"]["failed"] == 0
    assert len(kbenv["saved"]) == 8
    # state marked with kb_key for every article
    for sk in ("SpaceA", "SpaceB"):
        for art in arts[sk]:
            assert kb_key(sk, art["slug"]) in kbenv["state"].ids
    assert kbenv["idx_calls"], "generate_kb_index should run at end of a clean run"


def test_skip_already_scraped_unless_force(kbenv):
    cfg_state = {"tmp": kbenv["tmp"]}
    A = _space("SpaceA", lib="a")
    arts = [_art(1), _art(2), _art(3)]
    discover = lambda sk: arts
    # seed one already-scraped article
    kbenv["state"].mark(kb_key("SpaceA", "a1"))

    report, _, _ = _run([A], cfg_state=cfg_state, workers=2, force=False, discover=discover)
    assert report["spaces"]["SpaceA"]["skipped"] == 1
    assert report["spaces"]["SpaceA"]["new"] == 2

    # force=True re-scrapes everything
    report2, _, _ = _run([A], cfg_state=cfg_state, workers=2, force=True, discover=discover)
    assert report2["spaces"]["SpaceA"]["skipped"] == 0
    assert report2["spaces"]["SpaceA"]["new"] == 3


def test_frozen_article_times_out_and_is_bounded(kbenv, monkeypatch):
    # THE frozen-Chrome regression: one article's page.content() hangs forever. The
    # 90s outer wait_for (shrunk to 0.2s) must fire, the article is redispatched up to
    # MAX_ARTICLE_ATTEMPTS then failed, the run COMPLETES, and every other article saves.
    monkeypatch.setattr(kea, "ARTICLE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(kea, "_RECOVER_RETRY_DELAY", 0.01)
    cfg_state = {"tmp": kbenv["tmp"], "freeze_urls": {"https://kb/a2"}}
    A = _space("SpaceA", lib="a")
    arts = [_art(1), _art(2), _art(3), _art(4)]
    discover = lambda sk: arts

    report, cb, _ = _run([A], cfg_state=cfg_state, workers=2, discover=discover)
    assert report["spaces"]["SpaceA"]["failed"] == 1
    assert report["spaces"]["SpaceA"]["new"] == 3
    fa = report["failed_articles"]
    assert len(fa) == 1 and fa[0]["url"] == "https://kb/a2"
    assert fa[0]["error_type"] == "TimeoutError"
    assert fa[0]["space_key"] == "SpaceA" and fa[0]["slug"] == "a2"


def test_browser_death_recovers_never_mass_fails(kbenv, monkeypatch):
    # bug-145 mirror: the ONE shared browser dies after handing out the initial worker
    # tabs; a tab crash forces a rebuild that hits the corpse -> single-flight supervisor
    # recovery (fresh browser). The run COMPLETES with zero failures, all saved.
    monkeypatch.setattr(kea, "_RECOVER_RETRY_DELAY", 0.01)
    # one tab crash on a3 (first attempt) forces the rebuild that discovers the corpse
    cfg_state = {"tmp": kbenv["tmp"], "crashes": {},
                 "crash_rule": lambda url, n: url == "https://kb/a3" and n == 0}
    A = _space("SpaceA", lib="a")
    arts = [_art(i) for i in range(1, 7)]
    discover = lambda sk: arts

    report, cb, browsers = _run([A], cfg_state=cfg_state, workers=2, discover=discover,
                                die_after=2)   # 1st browser: 2 tabs then corpse
    assert report["totals"]["failed"] == 0, report
    assert report["spaces"]["SpaceA"]["new"] == 6
    assert any("recovered" in m for _, m in cb.logs), cb.logs
    assert len(browsers) == 2 and browsers[0].closed is True


def test_discovery_failure_marks_space_and_continues(kbenv):
    cfg_state = {"tmp": kbenv["tmp"]}
    A, B = _space("SpaceA", lib="a"), _space("SpaceB", lib="b")
    b_arts = [_art(1), _art(2), _art(3)]

    def discover(sk):
        if sk == "SpaceA":
            raise RuntimeError("discovery boom")
        return b_arts

    report, cb, _ = _run([A, B], cfg_state=cfg_state, workers=2, discover=discover)
    assert report["spaces"]["SpaceA"]["discovered"] == 0
    assert report["spaces"]["SpaceA"]["new"] == 0
    assert report["spaces"]["SpaceB"]["new"] == 3
    assert any(lvl == "error" and "SpaceA" in m for lvl, m in cb.logs), cb.logs


def test_explicit_items_mode_scrapes_only_those(kbenv):
    cfg_state = {"tmp": kbenv["tmp"]}
    A, B = _space("SpaceA", lib="a"), _space("SpaceB", lib="b")
    def raiser(sk):
        raise AssertionError("discovery must NOT be called in items mode")
    items = [(A, _art(1)), (B, _art(7))]

    report, _, _ = _run([A, B], cfg_state=cfg_state, workers=2, items=items, discover=raiser)
    assert report["totals"]["new"] == 2
    assert report["spaces"]["SpaceA"]["new"] == 1
    assert report["spaces"]["SpaceB"]["new"] == 1
    assert len(kbenv["saved"]) == 2
    assert {u for _, u in kbenv["saved"]} == {"https://kb/a1", "https://kb/a7"}


def test_post_run_audit_alert_fires(kbenv, monkeypatch):
    cfg_state = {"tmp": kbenv["tmp"]}
    A = _space("SpaceA", lib="a")
    arts = [_art(1), _art(2)]
    discover = lambda sk: arts

    # warning branch: audit reports missing > 0
    monkeypatch.setattr(kea, "audit_spaces", lambda cfgs, base: {
        "spaces": {}, "totals": {"discovered": 2, "on_disk": 1, "missing": 1,
                                 "spaces_with_errors": 0}})
    _, cb, _ = _run([A], cfg_state=cfg_state, workers=2, discover=discover, run_audit=True)
    warnings = [a for a in cb.alerts if a[0] == "warning"]
    assert len(warnings) == 1, cb.alerts
    assert "Retry Failures" in warnings[0][2]

    # info branch: nothing missing and nothing failed -> completeness confirmed
    monkeypatch.setattr(kea, "audit_spaces", lambda cfgs, base: {
        "spaces": {}, "totals": {"discovered": 2, "on_disk": 2, "missing": 0,
                                 "spaces_with_errors": 0}})
    _, cb2, _ = _run([A], cfg_state=cfg_state, workers=2, discover=discover, run_audit=True)
    infos = [a for a in cb2.alerts if a[0] == "info"]
    assert len(infos) == 1, cb2.alerts
    assert "verified" in infos[0][1].lower() or "present" in infos[0][2].lower()


def test_cancel_mid_run_stops_cleanly(kbenv):
    # Cancel after the first completion: the run must RETURN (no hang) and the remaining
    # articles must NOT be marked failed — they stay unscraped for the next run.
    cfg_state = {"tmp": kbenv["tmp"]}
    A = _space("SpaceA", lib="a")
    arts = [_art(i) for i in range(1, 9)]
    discover = lambda sk: arts
    control = RunControl()
    cb = RecCB()

    async def main():
        # a slow-ish first article gives us a window to cancel; but simplest: cancel from
        # a callback once the first on_progress fires.
        orig = cb.on_progress
        def stop_after_first(sk, title, done, total):
            orig(sk, title, done, total)
            if done >= 1:
                control.cancel()
        cb.on_progress = stop_after_first
        browsers = []
        def bf():
            b = FakeBrowser(cfg_state); browsers.append(b); return b
        return await asyncio.wait_for(kea.run_kb_scrape_async(
            [A], force=True, control=control, cb=cb, workers=2,
            output_base=cfg_state["tmp"], browser_factory=bf, discover=discover,
            run_audit=False), timeout=10)

    report = asyncio.run(main())
    assert report["totals"]["failed"] == 0            # nothing force-failed on cancel
    assert report["spaces"]["SpaceA"]["new"] < 8      # not everything got scraped
    assert not any(a[0] in ("warning", "error") for a in cb.alerts), cb.alerts
