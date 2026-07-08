import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.engine import Engine, EngineCallbacks, CancellationToken


class RecordingCallbacks(EngineCallbacks):
    def __init__(self):
        self.logs = []
        self.statuses = []
        self.progress = []
        self.started = []
        self.finished = []
    def on_log(self, level, msg): self.logs.append((level, msg))
    def on_status(self, product, stats): self.statuses.append((product, dict(stats)))
    def on_progress(self, product, version, idx, total): self.progress.append((product, version, idx, total))
    def on_started(self, action): self.started.append(action)
    def on_finished(self, action, report): self.finished.append((action, report))


def test_cancel_token_default():
    t = CancellationToken()
    assert t.is_cancelled() is False
    t.cancel()
    assert t.is_cancelled() is True


def test_default_callbacks_are_no_ops():
    c = EngineCallbacks()
    c.on_log("info", "x"); c.on_status("p", {}); c.on_progress("p", "1.0", 0, 1)
    c.on_started("a"); c.on_finished("a", {})


def test_engine_validate_emits_status_for_each_product(monkeypatch):
    cb = RecordingCallbacks()
    eng = Engine(callbacks=cb, cancel_token=CancellationToken())

    from scraper import engine as eng_mod
    def fake_discover(space_key, http_get=None):
        return [{"version": "1.0", "title": "Version 1.0.0", "url": "http://x", "page_id": "1"}]
    monkeypatch.setattr(eng_mod, "discover_versions", fake_discover)

    ok = eng.validate()
    assert ok is True
    products_logged = [m for lvl, m in cb.logs if "versions" in m]
    assert len(products_logged) >= 3


def test_scrape_product_respects_cancel(monkeypatch):
    cb = RecordingCallbacks()
    tok = CancellationToken()
    eng = Engine(callbacks=cb, cancel_token=tok)

    from scraper import engine as eng_mod
    fake_versions = [{"version": f"v{i}", "title": f"V{i}", "url": f"http://x/{i}", "page_id": str(i)} for i in range(5)]
    monkeypatch.setattr(eng_mod, "discover_versions", lambda key, http_get=None: fake_versions)

    class FakeBrowser:
        def __init__(self, *a, **k): self.calls = 0
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def navigate(self, url): self.calls += 1
        def expand_confluence_macros(self): pass
        def screenshot(self, path): pass
        def get_content(self): return "<html><body></body></html>"
    fake_browser_instance = FakeBrowser()
    monkeypatch.setattr(eng_mod, "Browser", lambda *a, **k: fake_browser_instance)

    tok.cancel()
    stats = eng.scrape_product("saleshub", force=True)
    assert stats["new"] == 0
    assert fake_browser_instance.calls == 0
