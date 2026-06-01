import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.kb_discovery import discover_articles, _slugify


def test_slugify_basic():
    assert _slugify("How to Configure Email") == "how_to_configure_email"


def test_slugify_special_chars():
    assert _slugify("Error: Cannot Start Application") == "error_cannot_start_application"


def test_slugify_truncates_at_120():
    assert len(_slugify("a" * 200)) <= 120


def test_discover_articles_empty_space():
    articles = discover_articles("SA", http_get=lambda url: {"results": [], "_links": {}})
    assert articles == []


def test_discover_articles_returns_correct_fields():
    mock = {
        "results": [
            {"title": "How to Do X", "_links": {"webui": "/display/SA/How+to+Do+X"}, "id": 123},
        ],
        "_links": {},
    }
    articles = discover_articles("SA", http_get=lambda url: mock)
    assert len(articles) == 1
    assert articles[0]["title"] == "How to Do X"
    assert articles[0]["slug"] == "how_to_do_x"
    assert articles[0]["page_id"] == "123"
    assert articles[0]["url"] == "https://help.contoso.example/display/SA/How+to+Do+X"


def test_discover_articles_deduplicates_by_url():
    mock = {
        "results": [
            {"title": "Article", "_links": {"webui": "/display/SA/Art"}, "id": 1},
            {"title": "Article Dupe", "_links": {"webui": "/display/SA/Art"}, "id": 2},
        ],
        "_links": {},
    }
    articles = discover_articles("SA", http_get=lambda url: mock)
    assert len(articles) == 1


def test_discover_articles_follows_pagination():
    page1 = {
        "results": [{"title": "A1", "_links": {"webui": "/display/SA/A1"}, "id": 1}],
        "_links": {"next": "/rest/api/content?spaceKey=SA&start=1"},
    }
    page2 = {
        "results": [{"title": "A2", "_links": {"webui": "/display/SA/A2"}, "id": 2}],
        "_links": {},
    }
    responses = [page1, page2]
    call_idx = [0]

    def mock_get(url):
        r = responses[call_idx[0]]
        call_idx[0] += 1
        return r

    articles = discover_articles("SA", http_get=mock_get)
    assert len(articles) == 2
    assert articles[0]["title"] == "A1"
    assert articles[1]["title"] == "A2"


def test_discover_articles_handles_absolute_next_link():
    page1 = {
        "results": [{"title": "A1", "_links": {"webui": "/display/SA/A1"}, "id": 1}],
        "_links": {"next": "https://help.contoso.example/rest/api/content?spaceKey=SA&start=1"},
    }
    page2 = {"results": [], "_links": {}}
    responses = [page1, page2]
    call_idx = [0]

    def mock_get(url):
        r = responses[call_idx[0]]
        call_idx[0] += 1
        return r

    articles = discover_articles("SA", http_get=mock_get)
    assert len(articles) == 1
