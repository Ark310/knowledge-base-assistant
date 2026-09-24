import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.discovery import extract_version, is_version_title, discover_versions

FIX = Path(__file__).parent / "fixtures"


def make_http_get(rest_file: str):
    """Return an http_get(url) that serves the captured combined fixture once,
    then signals no further pages (so the pagination loop terminates)."""
    if not (FIX / rest_file).exists():
        import pytest
        pytest.skip(f"captured REST payload {rest_file} is not shipped (real help-site content)")
    data = json.loads((FIX / rest_file).read_text(encoding="utf-8"))
    calls = {"n": 0}
    def http_get(url: str) -> dict:
        calls["n"] += 1
        if calls["n"] == 1:
            return {"results": data["results"], "_links": {}}
        return {"results": [], "_links": {}}
    return http_get


# extract_version
def test_extract_version_plain():
    assert extract_version("Version 3.0.1.9") == "3.0.1.9"

def test_extract_version_saleshub_prefix():
    assert extract_version("SalesHub WEB Version 2.0.2.1") == "2.0.2.1"

def test_extract_version_none_for_index():
    assert extract_version("SalesHub WEB Release Notes") is None

def test_extract_version_ignores_two_part_numbers():
    # "Web 4.0" has only one dot -> not a version
    assert extract_version("Web 4.0 Overview") is None


# is_version_title
def test_is_version_title_true():
    assert is_version_title("SalesHub WEB Version 2.0.2.1") is True

def test_is_version_title_false_howto():
    assert is_version_title("How-to articles") is False

def test_is_version_title_false_index():
    assert is_version_title("Release Notes") is False


# discover_versions against real captured REST data
def test_discover_saleshub_count_and_clean():
    items = discover_versions("SHReleaseNotes", make_http_get("saleshub_rest.json"))
    assert len(items) == 21
    titles = [i["title"] for i in items]
    assert "How-to articles" not in titles
    assert "SalesHub WEB Release Notes" not in titles

def test_discover_tradedesk_count():
    items = discover_versions("releasenotes", make_http_get("tradedesk_rest.json"))
    assert len(items) == 117

def test_discover_web4_count():
    items = discover_versions("ReleaseNotesWeb4", make_http_get("web4_rest.json"))
    assert len(items) == 18

def test_discover_item_shape():
    items = discover_versions("SHReleaseNotes", make_http_get("saleshub_rest.json"))
    sample = next(i for i in items if i["version"] == "2.0.2.1")
    assert sample["title"] == "SalesHub WEB Version 2.0.2.1"
    assert sample["url"] == "https://help.contoso.example/display/SHReleaseNotes/SalesHub+WEB+Version+2.0.2.1"
    assert sample["page_id"]  # non-empty string


def test_discover_disambiguates_duplicate_versions():
    # TradeDesk has both "Version 2.4.0.10" and "Version 2.4.0.10 EXT" which both
    # extract to 2.4.0.10. They must NOT collide (would overwrite each other on save).
    def http_get(url):
        return {"results": [
            {"id": "1", "title": "Version 2.4.0.10", "_links": {"webui": "/display/releasenotes/Version+2.4.0.10"}},
            {"id": "2", "title": "Version 2.4.0.10 EXT", "_links": {"webui": "/display/releasenotes/Version+2.4.0.10+EXT"}},
        ], "_links": {}}
    items = discover_versions("releasenotes", http_get)
    versions = [i["version"] for i in items]
    assert len(items) == 2
    assert len(set(versions)) == 2          # distinct
    assert "2.4.0.10" in versions
    assert "2.4.0.10-EXT" in versions       # tail appended for the duplicate
