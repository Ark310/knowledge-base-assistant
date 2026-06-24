# tests/test_kb_tab.py
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])
from scraper.kb_tab import KBTab
from scraper.kb_config import KB_PRODUCT_GROUPS

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
    """Clicking 'Scrape family' on a KB family dispatches scrape_family, not scrape_all."""
    captured = {}

    def fake_start_kb(action, kwargs=None):
        captured["action"] = action
        captured["kwargs"] = kwargs or {}

    t = KBTab()
    t._start_kb = fake_start_kb

    fam = next(iter(KB_PRODUCT_GROUPS))
    t._current_family = fam
    t._scrape_family(force=False)

    assert captured.get("action") == "scrape_family"
    assert captured.get("kwargs", {}).get("product_label") == fam
