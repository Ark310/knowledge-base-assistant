import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.writers.md_writer import save_version, render_md

DATA = {
    "product": "saleshub", "version": "2.0.2.1", "title": "SalesHub WEB Version 2.0.2.1",
    "url": "http://x", "scraped_at": "2026-05-27T10:00:00", "screenshot": "s.png",
    "enhancements": [
        {"sno": "1", "id": "57196", "details": "IBAN Validation", "risk": "LOW"},
        {"sno": "2", "id": "57200", "details": "Other", "risk": "LOW", "module": "X"},
    ],
    "schema_changes": [{"object_type": "Table", "object_name": "WEB_FTF_DETAIL", "action_type": "Altered"}],
}


def test_renders_title_and_version():
    md = render_md(DATA)
    assert "2.0.2.1" in md and "SalesHub WEB Version 2.0.2.1" in md

def test_renders_section_heading():
    md = render_md(DATA)
    assert "Enhancements" in md and "Schema Changes" in md

def test_renders_table_values():
    md = render_md(DATA)
    assert "57196" in md and "IBAN Validation" in md and "WEB_FTF_DETAIL" in md

def test_table_has_union_of_columns():
    # second enhancement row adds "module" -> column must appear in header
    md = render_md(DATA)
    assert "module" in md

def test_omits_absent_sections():
    md = render_md(DATA)
    assert "Bugs" not in md and "Tasks" not in md

def test_save_creates_md_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(DATA, Path(tmp))
        assert path.exists() and path.name == "2.0.2.1.md"
