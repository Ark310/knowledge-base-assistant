# tests/test_kb_tab.py
import json
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])
from scraper.kb_tab import KBTab
from scraper.kb_config import KB_PRODUCT_GROUPS, KB_SPACES_BY_KEY
import scraper.kb_tab as kb_tab
import scraper.run_registry as run_registry


@pytest.fixture(autouse=True)
def _reset_run_registry():
    """Keep the module-level single-run registry clean between tests — it is
    shared global state, so a test that acquires and doesn't release would
    otherwise leak into unrelated tests run later in the same session."""
    run_registry.release(run_registry.owner() or "")
    yield
    run_registry.release(run_registry.owner() or "")


@pytest.fixture(autouse=True)
def _isolate_kb_reports(tmp_path, monkeypatch):
    """bug-149 guard: point kb_tab's report-file constants at tmp_path so no
    test can read/write the operator's real state/last_kb_run_report.json or
    state/kb_audit_report.json."""
    monkeypatch.setattr(kb_tab, "KB_REPORT_FILE", tmp_path / "last_kb_run_report.json")
    monkeypatch.setattr(kb_tab, "KB_AUDIT_REPORT_FILE", tmp_path / "kb_audit_report.json")
    yield


class _NoOp:
    """Callable no-op that also acts as a signal (has .connect()) — mirrors
    test_ticket_tab.py's stub-worker convention."""
    def __call__(self, *a, **k): pass
    def connect(self, *a, **k): pass


def _stub_async_kb_worker(captured: dict):
    """Factory for a fake AsyncKBWorker that captures constructor kwargs
    instead of running a real (thread + asyncio + browser) scrape."""
    class _StubWorker:
        def __init__(self, *a, **k):
            captured["space_cfgs"] = a[0] if a else k.get("space_cfgs")
            captured.update(k)
        def __getattr__(self, name):
            return _NoOp()   # signals/.start()/.isRunning() — all no-op
    return _StubWorker


def test_rail_lists_families_plus_release_notes():
    t = KBTab()
    labels = [t.rail.item(i).text() for i in range(t.rail.count())]
    for fam in KB_PRODUCT_GROUPS:
        assert fam in labels
    assert "Release Notes" in labels

def test_detail_has_expected_columns():
    t = KBTab()
    headers = [t.detail.horizontalHeaderItem(i).text() for i in range(t.detail.columnCount())]
    assert headers[:5] == ["Space", "Found", "New", "Skip", "Fail"]

def test_selecting_family_populates_spaces():
    t = KBTab()
    fam = next(iter(KB_PRODUCT_GROUPS))
    t._populate_detail(fam)
    assert t.detail.rowCount() == len(KB_PRODUCT_GROUPS[fam])

def test_release_notes_family_lists_products():
    import scraper.config as config
    t = KBTab()
    t._populate_detail("Release Notes")
    assert t.detail.rowCount() == len(config.PRODUCTS)

def test_toolbar_and_pause_present():
    t = KBTab()
    for a in ("btn_validate", "btn_rebuild", "btn_scrape_all", "btn_force_all", "btn_pause", "btn_stop", "inp_filter"):
        assert getattr(t, a) is not None

def test_shutdown_no_worker_is_noop():
    KBTab().shutdown()

def test_scrape_family_kb_targets_scrape_family():
    """Clicking 'Scrape family' on a KB family dispatches AsyncKBWorker with
    just that family's own space_cfgs (v4.0.4 Task 7 — not the whole library
    via scrape_all). Full KB_PRODUCT_GROUPS cfg dicts must be used, not the
    rail's slim {key, display_name, engine_kind} shape."""
    captured = {}

    def fake_start_kb_async(*, space_cfgs, force, items=None, chain_rn=False):
        captured["space_cfgs"] = space_cfgs
        captured["force"] = force
        captured["items"] = items
        captured["chain_rn"] = chain_rn

    t = KBTab()
    t._start_kb_async = fake_start_kb_async

    fam = next(iter(KB_PRODUCT_GROUPS))
    t._current_family = fam
    t._scrape_family(force=False)

    assert captured.get("space_cfgs") == KB_PRODUCT_GROUPS[fam]
    assert captured.get("force") is False
    assert captured.get("items") is None


# ── v4.0.4 Task 7: workers/priority/monitor/alerts + Retry + Audit ──────────

def test_kb_scrape_uses_async_worker_with_spinner_workers(monkeypatch):
    """_scrape_family on a KB family constructs AsyncKBWorker with
    workers == spn_workers.value()."""
    captured = {}
    monkeypatch.setattr(kb_tab, "AsyncKBWorker", _stub_async_kb_worker(captured))

    t = kb_tab.KBTab()
    t.spn_workers.setValue(7)

    fam = next(iter(KB_PRODUCT_GROUPS))
    t._current_family = fam
    t._scrape_family(force=False)

    assert captured.get("workers") == 7
    assert captured.get("space_cfgs") == KB_PRODUCT_GROUPS[fam]


def test_retry_button_builds_items_from_report(monkeypatch):
    """A fake KB_REPORT_FILE with 2 failed_articles + 1 audit-missing (one
    duplicated with a failed article) → clicking retry constructs
    AsyncKBWorker with the deduped 2-item set and force=True."""
    space_key = next(iter(KB_SPACES_BY_KEY))
    report = {
        "failed_articles": [
            {"space_key": space_key, "title": "A", "url": "https://x/a", "slug": "a"},
            {"space_key": space_key, "title": "B", "url": "https://x/b", "slug": "b"},
        ],
        "audit": {
            "spaces": {
                space_key: {
                    "display_name": "x", "discovered": 5, "on_disk": 3,
                    "missing": [
                        # duplicate of the 'a' failed_article above — must NOT
                        # inflate the discovered count.
                        {"space_key": space_key, "title": "A", "url": "https://x/a", "slug": "a"},
                    ],
                    "error": None,
                }
            },
            "totals": {},
        },
        "totals": {},
    }
    kb_tab.KB_REPORT_FILE.write_text(json.dumps(report), encoding="utf-8")

    captured = {}
    monkeypatch.setattr(kb_tab, "AsyncKBWorker", _stub_async_kb_worker(captured))

    t = kb_tab.KBTab()
    assert t.btn_retry.isEnabled()

    t._on_retry_clicked()

    items = captured.get("items")
    assert items is not None and len(items) == 2
    assert {m["slug"] for _cfg, m in items} == {"a", "b"}
    assert all(_cfg["space_key"] == space_key for _cfg, _ in items)
    assert captured.get("force") is True


def test_retry_disabled_when_report_clean():
    """Report with no failures/missing → btn_retry disabled."""
    report = {"failed_articles": [], "audit": {"spaces": {}, "totals": {}}, "totals": {}}
    kb_tab.KB_REPORT_FILE.write_text(json.dumps(report), encoding="utf-8")

    t = kb_tab.KBTab()

    assert not t.btn_retry.isEnabled()


def test_audit_button_writes_report_and_enables_retry(monkeypatch):
    """Monkeypatch audit_spaces → result with 1 missing; click audit; report
    file written; btn_retry enabled; alert slot called."""
    def fake_audit_spaces(space_cfgs, output_base):
        return {
            "spaces": {
                "SA": {"display_name": "System Administration", "discovered": 5,
                       "on_disk": 4,
                       "missing": [{"space_key": "SA", "title": "T",
                                    "url": "https://x/t", "slug": "t"}],
                       "error": None},
            },
            "totals": {"discovered": 5, "on_disk": 4, "missing": 1, "spaces_with_errors": 0},
        }
    monkeypatch.setattr(kb_tab, "audit_spaces", fake_audit_spaces)

    t = kb_tab.KBTab()
    alerts = []
    t._on_alert = lambda sev, title, body: alerts.append((sev, title, body))

    t._start_audit()
    loop = QEventLoop()
    t.worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    t.worker.wait(2000)

    assert kb_tab.KB_AUDIT_REPORT_FILE.exists()
    written = json.loads(kb_tab.KB_AUDIT_REPORT_FILE.read_text(encoding="utf-8"))
    assert written["totals"]["missing"] == 1
    assert t.btn_retry.isEnabled()
    assert alerts and alerts[0][0] == "warning"


def test_alert_slot_nonmodal():
    """_on_alert('error','T','B') → _alert_box exists, windowModality() == Qt.NonModal."""
    t = KBTab()
    t._on_alert("error", "T", "B")
    assert t._alert_box is not None
    assert t._alert_box.windowModality() == Qt.NonModal
