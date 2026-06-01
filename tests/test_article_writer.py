import json
from pathlib import Path
import pytest
from scraper.writers.article_writer import save_article, safe_slug


def test_safe_slug_basic():
    assert safe_slug("How to Configure Email") == "how_to_configure_email"


def test_safe_slug_special_chars():
    assert safe_slug("Error: Cannot Start!") == "error_cannot_start"


def test_safe_slug_max_length():
    assert len(safe_slug("x" * 300)) <= 120


def test_safe_slug_empty_fallback():
    assert safe_slug("!!!") == "untitled"


def _sample_data() -> dict:
    return {
        "space_key": "SA",
        "space_name": "System Administration",
        "product": "tradedesk",
        "title": "How to Configure Email",
        "url": "https://help.contoso.example/display/SA/How+to+Configure+Email",
        "scraped_at": "2026-06-01T12:00:00",
        "screenshot": "/tmp/shot.png",
        "body_md": "## Instructions\n\n1. Go to System Admin",
    }


def _sample_cfg() -> dict:
    return {"product": "tradedesk", "lib_folder": "system_administration"}


def test_save_article_creates_json_and_md(tmp_path):
    save_article(_sample_data(), tmp_path, _sample_cfg())
    base = tmp_path / "tradedesk" / "system_administration"
    assert (base / "how_to_configure_email.json").exists()
    assert (base / "how_to_configure_email.md").exists()


def test_save_article_json_content(tmp_path):
    save_article(_sample_data(), tmp_path, _sample_cfg())
    json_file = tmp_path / "tradedesk" / "system_administration" / "how_to_configure_email.json"
    loaded = json.loads(json_file.read_text(encoding="utf-8"))
    assert loaded["title"] == "How to Configure Email"
    assert loaded["space_key"] == "SA"
    assert loaded["body_md"] == "## Instructions\n\n1. Go to System Admin"


def test_save_article_md_has_yaml_frontmatter(tmp_path):
    save_article(_sample_data(), tmp_path, _sample_cfg())
    md_file = tmp_path / "tradedesk" / "system_administration" / "how_to_configure_email.md"
    content = md_file.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "title: How to Configure Email" in content
    assert "space: System Administration" in content
    assert "product: tradedesk" in content
    assert "---" in content


def test_save_article_md_body_follows_frontmatter(tmp_path):
    save_article(_sample_data(), tmp_path, _sample_cfg())
    md_file = tmp_path / "tradedesk" / "system_administration" / "how_to_configure_email.md"
    content = md_file.read_text(encoding="utf-8")
    assert "## Instructions" in content
    assert "1. Go to System Admin" in content


def test_save_article_creates_parent_dirs(tmp_path):
    cfg = {"product": "web2", "lib_folder": "payments"}
    data = _sample_data()
    data["product"] = "web2"
    save_article(data, tmp_path, cfg)
    assert (tmp_path / "web2" / "payments").is_dir()
