import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.parsers.ticket_parser import (
    is_not_found,
    parse_ticket_fields,
    parse_comments,
    parse_resolution,
    parse_files,
    parse_ticket_detail,
)

FIX = Path(__file__).parent / "fixtures" / "tradedesk"


def html(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


DETAIL_HTML = html("ticket_detail.html")
RESOLUTION_HTML = html("resolution.html")
FILES_HTML = html("files.html")
NOT_FOUND_HTML = html("not_found.html")


# ── is_not_found ──────────────────────────────────────────────────────────────

def test_is_not_found_returns_true_for_not_found_page():
    assert is_not_found(NOT_FOUND_HTML) is True


def test_is_not_found_returns_false_for_ticket_detail():
    assert is_not_found(DETAIL_HTML) is False


def test_is_not_found_empty_html_is_not_found():
    assert is_not_found("") is True


# ── parse_ticket_fields ───────────────────────────────────────────────────────

def test_fields_ticket_id():
    f = parse_ticket_fields(DETAIL_HTML)
    assert f["ticket_id"] == "76511"


def test_fields_product():
    f = parse_ticket_fields(DETAIL_HTML)
    assert f["product"] == "TD Client Server"


def test_fields_priority():
    f = parse_ticket_fields(DETAIL_HTML)
    assert f["priority"] == "high"


def test_fields_status_starts_with_18():
    f = parse_ticket_fields(DETAIL_HTML)
    assert f["status"].startswith("18 - ")


def test_fields_organization():
    f = parse_ticket_fields(DETAIL_HTML)
    assert f["organization"] == "Northwind Trading"


def test_fields_assignee_non_empty():
    f = parse_ticket_fields(DETAIL_HTML)
    assert f.get("assignee", "")


def test_fields_csqa_owner_non_empty():
    f = parse_ticket_fields(DETAIL_HTML)
    assert f.get("csqa_owner", "")


def test_fields_title_non_empty():
    f = parse_ticket_fields(DETAIL_HTML)
    assert f.get("title", "")


def test_fields_created_at_matches_date_pattern():
    f = parse_ticket_fields(DETAIL_HTML)
    assert re.match(r"\d{2}/\d{2}/\d{4}", f.get("created_at", ""))


def test_fields_dedupe_first_wins():
    # Organization appears twice; only first occurrence should be captured
    f = parse_ticket_fields(DETAIL_HTML)
    assert f["organization"] == "Northwind Trading"
    # Verify no duplicate keys by counting: dict can't have dupes anyway,
    # but ensure status comes from first set too
    assert f["status"] == "18 - Internal CSQA UAT"


def test_fields_awaiting_production_deployment_false():
    # Fixture checkbox has no "checked" attribute
    f = parse_ticket_fields(DETAIL_HTML)
    assert f.get("awaiting_production_deployment") is False


# ── parse_comments ────────────────────────────────────────────────────────────

def test_comments_count():
    comments = parse_comments(DETAIL_HTML)
    assert len(comments) == 3


def test_comment_ids_are_digit_strings():
    comments = parse_comments(DETAIL_HTML)
    for c in comments:
        assert c["id"].isdigit()


def test_first_comment_author():
    comments = parse_comments(DETAIL_HTML)
    assert comments[0]["author"] == "Jordan Lee"


def test_first_comment_is_internal():
    comments = parse_comments(DETAIL_HTML)
    assert comments[0]["internal"] is True


def test_second_comment_not_internal():
    comments = parse_comments(DETAIL_HTML)
    assert comments[1]["internal"] is False


def test_comment_dates_non_empty():
    comments = parse_comments(DETAIL_HTML)
    for c in comments:
        assert c["date"], f"comment {c['id']} has empty date"


def test_comment_bodies_non_empty():
    comments = parse_comments(DETAIL_HTML)
    for c in comments:
        assert c["body"], f"comment {c['id']} has empty body"


def test_exactly_one_comment_has_attachments():
    comments = parse_comments(DETAIL_HTML)
    with_attachments = [c for c in comments if c.get("attachments")]
    assert len(with_attachments) == 1


def test_comment_attachment_label_contains_error_log():
    comments = parse_comments(DETAIL_HTML)
    with_attachments = [c for c in comments if c.get("attachments")]
    label = with_attachments[0]["attachments"][0]["label"]
    assert "error-log.txt" in label


# ── parse_resolution ──────────────────────────────────────────────────────────

def test_resolution_text_non_empty():
    r = parse_resolution(RESOLUTION_HTML)
    assert r["text"]


def test_resolution_attachments_count():
    r = parse_resolution(RESOLUTION_HTML)
    assert len(r["attachments"]) == 1


def test_resolution_attachment_label_contains_sql():
    r = parse_resolution(RESOLUTION_HTML)
    assert "resolution-script.sql" in r["attachments"][0]["label"]


def test_resolution_does_not_count_comment_downloads():
    # resolution.html has a comment section below the resolution-container;
    # its download button must not be counted in parse_resolution
    r = parse_resolution(RESOLUTION_HTML)
    assert len(r["attachments"]) == 1


# ── parse_files ───────────────────────────────────────────────────────────────

def test_files_count():
    files = parse_files(FILES_HTML)
    assert len(files) == 2


def test_files_labels_non_empty():
    files = parse_files(FILES_HTML)
    for f in files:
        assert f["label"], "a file entry has an empty label"


# ── parse_ticket_detail ───────────────────────────────────────────────────────

def test_ticket_detail_returns_empty_for_not_found():
    result = parse_ticket_detail(NOT_FOUND_HTML, "99999", "https://portal.contoso.example")
    assert result == {}


def test_ticket_detail_ticket_id():
    result = parse_ticket_detail(DETAIL_HTML, "76511", "https://portal.contoso.example")
    assert result["ticket_id"] == "76511"


def test_ticket_detail_product():
    result = parse_ticket_detail(DETAIL_HTML, "76511", "https://portal.contoso.example")
    assert result["product"] == "TD Client Server"


def test_ticket_detail_comments_count():
    result = parse_ticket_detail(DETAIL_HTML, "76511", "https://portal.contoso.example")
    assert len(result["comments"]) == 3


def test_ticket_detail_url():
    result = parse_ticket_detail(DETAIL_HTML, "76511", "https://portal.contoso.example")
    assert result["url"] == "https://portal.contoso.example/tickets/76511/edit"


def test_ticket_detail_scraped_at_present():
    result = parse_ticket_detail(DETAIL_HTML, "76511", "https://portal.contoso.example")
    assert result.get("scraped_at")
