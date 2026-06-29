"""Tests for the contoso (legacy ASP.NET) ticket parser — canonical schema output."""
from __future__ import annotations
from pathlib import Path

import pytest

from scraper.parsers.contoso_parser import (
    is_not_found,
    parse_resolution,
    parse_ticket_detail,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "contoso"


def _read(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


# ── is_not_found ──────────────────────────────────────────────────────────────

def test_is_not_found_true_on_not_found_fixture():
    html = _read("not_found.html")
    assert is_not_found(html, "99999") is True


def test_is_not_found_false_on_detail_fixture():
    html = _read("ticket_detail.html")
    assert is_not_found(html, "12345") is False


# ── parse_ticket_detail ───────────────────────────────────────────────────────

def test_parse_ticket_detail_returns_ticket_id_key():
    html = _read("ticket_detail.html")
    result = parse_ticket_detail(html, "12345", "https://support.contoso.example")
    assert "ticket_id" in result
    assert result["ticket_id"] == "12345"


def test_parse_ticket_detail_url_uses_edit_bug_aspx():
    html = _read("ticket_detail.html")
    result = parse_ticket_detail(html, "12345", "https://support.contoso.example")
    assert result["url"] == "https://support.contoso.example/edit_bug.aspx?id=12345"


def test_parse_ticket_detail_parses_product_field():
    html = _read("ticket_detail.html")
    result = parse_ticket_detail(html, "12345", "https://support.contoso.example")
    assert result.get("product") == "TradeDesk Demo"


def test_parse_ticket_detail_parses_organization_field():
    html = _read("ticket_detail.html")
    result = parse_ticket_detail(html, "12345", "https://support.contoso.example")
    assert result.get("organization") == "Acme Corp"


def test_parse_ticket_detail_has_comments_key():
    html = _read("ticket_detail.html")
    result = parse_ticket_detail(html, "12345", "https://support.contoso.example")
    assert "comments" in result
    assert isinstance(result["comments"], list)


def test_parse_ticket_detail_comments_count():
    html = _read("ticket_detail.html")
    result = parse_ticket_detail(html, "12345", "https://support.contoso.example")
    # Fixture has 2 comment rows
    assert len(result["comments"]) >= 1


def test_parse_ticket_detail_comment_has_canonical_keys():
    html = _read("ticket_detail.html")
    result = parse_ticket_detail(html, "12345", "https://support.contoso.example")
    comment = result["comments"][0]
    assert "id" in comment
    assert "author" in comment
    assert "date" in comment
    assert "internal" in comment
    assert "body" in comment
    assert "images" in comment
    assert "attachments" in comment


def test_parse_ticket_detail_comment_with_inline_image():
    """The second comment in the fixture contains a 1px PNG as inline base64."""
    html = _read("ticket_detail.html")
    result = parse_ticket_detail(html, "12345", "https://support.contoso.example")
    # Find the comment that carries an image
    image_comments = [c for c in result["comments"] if c.get("images")]
    assert len(image_comments) >= 1
    img = image_comments[0]["images"][0]
    assert "mime" in img
    assert "data" in img
    assert img["mime"] == "image/png"
    # Confirm it is base64 (non-empty string)
    assert isinstance(img["data"], str) and len(img["data"]) > 0


def test_parse_ticket_detail_has_empty_resolution_skeleton():
    html = _read("ticket_detail.html")
    result = parse_ticket_detail(html, "12345", "https://support.contoso.example")
    res = result.get("resolution")
    assert isinstance(res, dict)
    assert "text" in res
    assert "comments" in res
    assert "attachments" in res
    assert res["text"] == ""
    assert res["comments"] == []
    assert res["attachments"] == []


def test_parse_ticket_detail_has_empty_attachments():
    html = _read("ticket_detail.html")
    result = parse_ticket_detail(html, "12345", "https://support.contoso.example")
    assert "attachments" in result
    assert result["attachments"] == []


def test_parse_ticket_detail_returns_empty_on_not_found():
    html = _read("not_found.html")
    result = parse_ticket_detail(html, "99999", "https://support.contoso.example")
    assert result == {}


# ── parse_resolution ──────────────────────────────────────────────────────────

def test_parse_resolution_returns_dict():
    html = _read("resolution.html")
    result = parse_resolution(html)
    assert isinstance(result, dict)


def test_parse_resolution_has_required_keys():
    html = _read("resolution.html")
    result = parse_resolution(html)
    assert "text" in result
    assert "comments" in result
    assert "attachments" in result


def test_parse_resolution_text_non_empty():
    html = _read("resolution.html")
    result = parse_resolution(html)
    assert isinstance(result["text"], str)
    assert len(result["text"]) > 0


def test_parse_resolution_text_contains_expected_content():
    html = _read("resolution.html")
    result = parse_resolution(html)
    # Should contain text from the textarea
    assert "cache" in result["text"].lower() or "login" in result["text"].lower()


def test_parse_resolution_comments_is_list():
    html = _read("resolution.html")
    result = parse_resolution(html)
    assert isinstance(result["comments"], list)


def test_parse_resolution_attachments_is_list():
    html = _read("resolution.html")
    result = parse_resolution(html)
    assert isinstance(result["attachments"], list)


def test_parse_resolution_empty_html():
    result = parse_resolution("")
    assert result == {"text": "", "comments": [], "attachments": []}


def test_parse_resolution_not_found_html():
    result = parse_resolution("<html><body>Ticket not found</body></html>")
    assert result == {"text": "", "comments": [], "attachments": []}
