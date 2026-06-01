import json
from pathlib import Path
import pytest
from scraper.writers.kb_index_generator import generate_kb_index


def _write_article(base: Path, product: str, lib_folder: str, slug: str, title: str, space_key: str, space_name: str):
    d = base / product / lib_folder
    d.mkdir(parents=True, exist_ok=True)
    data = {
        "space_key": space_key, "space_name": space_name, "product": product,
        "title": title, "url": f"https://x.com/{slug}",
        "scraped_at": "2026-06-01T12:00:00", "screenshot": "", "body_md": "body",
    }
    (d / f"{slug}.json").write_text(json.dumps(data), encoding="utf-8")


def test_generate_kb_index_creates_both_files(tmp_path):
    _write_article(tmp_path, "tradedesk", "system_administration", "art1", "Article 1", "SA", "System Admin")
    generate_kb_index(tmp_path, [])
    assert (tmp_path / "index.json").exists()
    assert (tmp_path / "index.md").exists()


def test_index_json_contains_article(tmp_path):
    _write_article(tmp_path, "tradedesk", "system_administration", "art1", "Article 1", "SA", "System Admin")
    generate_kb_index(tmp_path, [])
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["total"] == 1
    assert index["articles"][0]["title"] == "Article 1"
    assert index["articles"][0]["space_key"] == "SA"


def test_index_json_excludes_index_file_itself(tmp_path):
    _write_article(tmp_path, "tradedesk", "system_administration", "art1", "Article 1", "SA", "System Admin")
    generate_kb_index(tmp_path, [])
    generate_kb_index(tmp_path, [])  # second call — index.json should not appear in results
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["total"] == 1


def test_index_md_contains_product_heading(tmp_path):
    _write_article(tmp_path, "tradedesk", "system_administration", "art1", "Article 1", "SA", "System Admin")
    generate_kb_index(tmp_path, [])
    md = (tmp_path / "index.md").read_text()
    assert "## TradeDesk KB" in md


def test_index_md_contains_article_row(tmp_path):
    _write_article(tmp_path, "tradedesk", "system_administration", "art1", "Article 1", "SA", "System Admin")
    generate_kb_index(tmp_path, [])
    md = (tmp_path / "index.md").read_text()
    assert "Article 1" in md
