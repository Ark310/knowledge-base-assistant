import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.parsers.universal import parse_page, normalize_header, _extract_version
from scraper.config import COLUMN_SYNONYMS

FIX = Path(__file__).parent / "fixtures"
ALIASES = {
    "enhancements": ["enhancements and new features", "enhancements", "new features"],
    "bugs": ["bugs", "bug fixes"],
    "schema_changes": ["schema changes", "database changes"],
    "tasks": ["tasks"],
}


def html(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def parse(name, product, version, title):
    url = f"http://example/{version}"
    return parse_page(html(name), product, version, title, url, "shot.png", ALIASES, COLUMN_SYNONYMS)


# normalize_header
def test_normalize_known_synonym():
    assert normalize_header("S.No", COLUMN_SYNONYMS) == "sno"

def test_normalize_tfs_id_variants():
    assert normalize_header("TFS/Portal ID", COLUMN_SYNONYMS) == "id"
    assert normalize_header("Portal/TFS ID", COLUMN_SYNONYMS) == "id"
    assert normalize_header("Task ID", COLUMN_SYNONYMS) == "id"

def test_normalize_risk_blob_prefix():
    blob = "Risk assessment: High: Requires a high degree of actionMedium: ...Low: ..."
    assert normalize_header(blob, COLUMN_SYNONYMS) == "risk"

def test_normalize_unknown_is_slugified():
    assert normalize_header("Object Type", COLUMN_SYNONYMS) == "object_type"
    assert normalize_header("Action Type", COLUMN_SYNONYMS) == "action_type"


# _extract_version
def test_extract_version_from_title():
    assert _extract_version("SalesHub WEB Version 2.0.2.1") == "2.0.2.1"


# SalesHub real page
def test_saleshub_sections_present():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    assert "enhancements" in r and "bugs" in r and "schema_changes" in r

def test_saleshub_row_counts():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    assert len(r["enhancements"]) == 8
    assert len(r["bugs"]) == 3
    assert len(r["schema_changes"]) == 1

def test_saleshub_first_enhancement_id():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    assert r["enhancements"][0]["id"] == "57196"
    assert r["enhancements"][0]["risk"] == "LOW"

def test_saleshub_schema_columns_preserved():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    row = r["schema_changes"][0]
    assert row["object_type"] == "Table"
    assert row["object_name"] == "WEB_FTF_DETAIL"
    assert row["action_type"] == "Altered"

def test_saleshub_ignores_table_of_contents():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    assert "table_of_contents" not in r and "tasks" not in r


# Web4 real page
def test_web4_tasks_and_schema_only():
    r = parse("web4_real.html", "web4", "4.0.3.0", "Version 4.0.3.0")
    assert "tasks" in r and "schema_changes" in r
    assert "enhancements" not in r and "bugs" not in r

def test_web4_row_counts():
    r = parse("web4_real.html", "web4", "4.0.3.0", "Version 4.0.3.0")
    assert len(r["tasks"]) == 4
    assert len(r["schema_changes"]) == 29

def test_web4_first_task_id():
    r = parse("web4_real.html", "web4", "4.0.3.0", "Version 4.0.3.0")
    assert r["tasks"][0]["id"] == "71669"


# TradeDesk real page
def test_tradedesk_row_counts():
    r = parse("tradedesk_real.html", "tradedesk", "3.0.1.9", "Version 3.0.1.9")
    assert len(r["enhancements"]) == 9
    assert len(r["bugs"]) == 3
    assert len(r["schema_changes"]) == 9

def test_tradedesk_module_column_captured():
    r = parse("tradedesk_real.html", "tradedesk", "3.0.1.9", "Version 3.0.1.9")
    assert r["enhancements"][0]["id"] == "14093"
    assert r["enhancements"][0]["module"] == "Dashboard Activity"


# Metadata
def test_metadata_fields():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    assert r["product"] == "saleshub"
    assert r["version"] == "2.0.2.1"
    assert r["title"] == "SalesHub WEB Version 2.0.2.1"
    assert r["screenshot"] == "shot.png"
    assert "scraped_at" in r and r["url"].endswith("2.0.2.1")
