import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.writers.index_generator import generate_all

PRODUCTS = {
    "tradedesk": {"display_name": "TradeDesk"},
    "web4": {"display_name": "Web4"},
    "saleshub": {"display_name": "SalesHub"},
}
V1 = {
    "product": "tradedesk", "version": "3.0.1.9", "title": "Version 3.0.1.9",
    "url": "http://x/3.0.1.9", "scraped_at": "2026-05-27T10:00:00", "screenshot": "",
    "enhancements": [{"id": "14093", "details": "Dashboard Activity"}],
    "bugs": [{"id": "14081", "details": "F10 key bug"}],
}
V2 = {
    "product": "tradedesk", "version": "3.0.1.8", "title": "Version 3.0.1.8",
    "url": "http://x/3.0.1.8", "scraped_at": "2026-05-27T09:00:00", "screenshot": "",
    "enhancements": [{"id": "13000", "details": "Earlier feature"}],
}
W1 = {
    "product": "web4", "version": "4.0.3.0", "title": "Version 4.0.3.0",
    "url": "http://x/4.0.3.0", "scraped_at": "2026-05-27T10:00:00", "screenshot": "",
    "tasks": [{"id": "71669", "details": "Quick Pay"}],
}


def write(lib, items):
    for v in items:
        d = lib / v["product"] / "versions"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{v['version']}.json").write_text(json.dumps(v), encoding="utf-8")


def test_changelog_lists_versions_newest_first():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp); write(lib, [V1, V2]); generate_all(lib, PRODUCTS)
        text = (lib / "tradedesk" / "CHANGELOG.md").read_text(encoding="utf-8")
        assert text.index("3.0.1.9") < text.index("3.0.1.8")

def test_features_list_includes_enhancements_and_tasks():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp); write(lib, [V1, W1]); generate_all(lib, PRODUCTS)
        fx = (lib / "tradedesk" / "features-list.md").read_text(encoding="utf-8")
        w4 = (lib / "web4" / "features-list.md").read_text(encoding="utf-8")
        assert "Dashboard Activity" in fx
        assert "Quick Pay" in w4   # tasks appear in features list

def test_bugs_list_includes_bugs():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp); write(lib, [V1]); generate_all(lib, PRODUCTS)
        text = (lib / "tradedesk" / "bugs-list.md").read_text(encoding="utf-8")
        assert "F10 key bug" in text

def test_master_index_lists_all_products_with_counts():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp); write(lib, [V1, V2, W1]); generate_all(lib, PRODUCTS)
        idx = (lib / "INDEX.md").read_text(encoding="utf-8")
        assert "TradeDesk" in idx and "Web4" in idx and "SalesHub" in idx
        assert "2 version" in idx  # tradedesk has 2

def test_empty_products_do_not_raise():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp); generate_all(lib, PRODUCTS)
        assert (lib / "INDEX.md").exists()
