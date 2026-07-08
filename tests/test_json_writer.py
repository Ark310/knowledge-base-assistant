import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.writers.json_writer import save_version

SAMPLE = {
    "product": "saleshub", "version": "2.0.2.1", "title": "SalesHub WEB Version 2.0.2.1",
    "url": "http://x", "scraped_at": "2026-05-27T10:00:00", "screenshot": "s.png",
    "enhancements": [{"sno": "1", "id": "57196", "details": "IBAN", "risk": "LOW"}],
    "schema_changes": [{"object_type": "Table", "object_name": "WEB_FTF_DETAIL", "action_type": "Altered"}],
}


def test_creates_json_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(SAMPLE, Path(tmp))
        assert path.exists() and path.suffix == ".json"

def test_path_uses_product_and_version():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(SAMPLE, Path(tmp))
        assert "saleshub" in str(path) and "versions" in str(path) and path.name == "2.0.2.1.json"

def test_content_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(SAMPLE, Path(tmp))
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["enhancements"][0]["id"] == "57196"
        assert loaded["schema_changes"][0]["object_name"] == "WEB_FTF_DETAIL"

def test_slash_in_version_becomes_dash():
    data = {**SAMPLE, "version": "2.0/EXT"}
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(data, Path(tmp))
        assert "/" not in path.name and path.name == "2.0-EXT.json"
