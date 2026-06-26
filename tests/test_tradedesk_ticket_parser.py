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
    assert f["title"] == "Northwind Trading - Org configuration and scripts"


def test_fields_created_at_matches_date_pattern():
    f = parse_ticket_fields(DETAIL_HTML)
    assert re.match(r"\d{2}/\d{2}/\d{4}", f.get("created_at", ""))


def test_fields_dedupe_first_wins():
    # Synthetic HTML with TWO Organization buttons carrying DIFFERENT values —
    # confirms that the deduplication logic (first-occurrence wins) is actually exercised.
    synthetic = """
    <html><body>
      <button class="floating-dropdown-btn">
        <span class="floating-dropdown-label">Organization<span class="text-red-500">*</span></span>
        <span class="floating-dropdown-value">Alpha Org</span>
      </button>
      <button class="floating-dropdown-btn">
        <span class="floating-dropdown-label">Organization<span class="text-red-500">*</span></span>
        <span class="floating-dropdown-value">Beta Org</span>
      </button>
    </body></html>
    """
    f = parse_ticket_fields(synthetic)
    assert f["organization"] == "Alpha Org"


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


def test_comments_have_no_inline_attachments():
    # On this portal the comment cards do NOT carry file labels — files are aggregated in
    # the Files sub-view (parse_files) and the resolution (parse_resolution). So the
    # detail-page comments parse with empty attachment lists.
    comments = parse_comments(DETAIL_HTML)
    assert all(c.get("attachments") == [] for c in comments)


def test_internal_badge_exact_text_not_body_prose():
    # Real comment structure: card div.(...)rounded-lg.border.bg-white; header text
    # "comment N posted by " in span.hidden + a SEPARATE <a> author; body in
    # div.comment-html-content. Card 1 has a <span>Internal</span> badge → internal True;
    # card 2's BODY merely contains the word "internal" with no badge → internal False.
    synthetic = """
    <html><body>
      <div class="space-y-2 sm:space-y-4">
        <div class="p-2 sm:p-4 rounded-lg border bg-white">
          <div class="flex-1 min-w-0">
            <span class="text-xs"><span class="truncate"><span class="hidden sm:inline">comment 1001 posted by </span><a class="text-blue-600" href="#">Jordan Lee</a></span></span>
            <span class="badge">Internal</span>
            <span>Jun 22, 2026 at 12:00 PM</span>
            <div class="comment-html-content"><p>Completed the work.</p></div>
          </div>
        </div>
        <div class="p-2 sm:p-4 rounded-lg border bg-white">
          <div class="flex-1 min-w-0">
            <span class="text-xs"><span class="truncate"><span class="hidden sm:inline">comment 1002 posted by </span><a class="text-blue-600" href="#">Alex Kim</a></span></span>
            <span>Jun 21, 2026 at 3:00 PM</span>
            <div class="comment-html-content"><p>Checked the internal lookup table and it looks fine.</p></div>
          </div>
        </div>
      </div>
    </body></html>
    """
    comments = parse_comments(synthetic)
    assert len(comments) == 2
    assert comments[0]["id"] == "1001" and comments[0]["author"] == "Jordan Lee"
    assert comments[0]["internal"] is True,  "badge card must be internal=True"
    assert comments[1]["internal"] is False, "body-prose 'internal' must NOT set internal=True"


def test_comment_extracts_inline_data_image():
    # Comments embed screenshots as base64 data-URI <img> in div.comment-html-content.
    png = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAf"
           "FcSJAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    synthetic = f"""
    <html><body><div class="space-y-2 sm:space-y-4">
      <div class="p-2 sm:p-4 rounded-lg border bg-white">
        <div class="flex-1 min-w-0">
          <span class="text-xs"><span class="truncate"><span class="hidden sm:inline">comment 2001 posted by </span><a class="text-blue-600" href="#">Jordan Lee</a></span></span>
          <span>Jun 22, 2026 at 12:00 PM</span>
          <div class="comment-html-content"><p>See screenshot:</p><p><img src="{png}"></p></div>
        </div>
      </div>
    </div></body></html>
    """
    cs = parse_comments(synthetic)
    assert len(cs) == 1
    assert len(cs[0]["images"]) == 1
    assert cs[0]["images"][0]["mime"] == "image/png"
    assert cs[0]["images"][0]["data"].startswith("iVBOR")


def test_comment_without_image_has_empty_images():
    cs = parse_comments(DETAIL_HTML)
    assert all(c.get("images") == [] for c in cs)


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


def test_resolution_counts_only_icon_download_not_comment_text():
    # The real resolution file is an ICON button[title="Download"]. A comment's text
    # "Download" button rendered INSIDE the resolution panel must NOT be counted as a
    # resolution attachment (icon_only scoping).
    synthetic = """
    <html><body>
      <div class="resolution-container">
        <div class="post-content"><p>Fix applied.</p>
          <div class="bg-gray-50 rounded-lg">
            <div class="min-w-0"><p class="text-sm break-words">resolution-script.sql</p></div>
            <button class="p-1.5" title='"Download"'></button>
          </div>
        </div>
        <div class="p-2 rounded-lg border bg-white">
          <div class="comment-html-content"><p>see attached</p></div>
          <div class="min-w-0"><span class="filename">comment-file.txt</span></div>
          <button class="inline-flex">Download</button>
        </div>
      </div>
    </body></html>
    """
    r = parse_resolution(synthetic)
    assert len(r["attachments"]) == 1, "only the icon download is a resolution file"
    assert "resolution-script.sql" in r["attachments"][0]["label"]


def test_resolution_always_has_comments_key():
    # canonical schema: resolution always carries text/comments/attachments
    r = parse_resolution(RESOLUTION_HTML)
    assert "comments" in r and isinstance(r["comments"], list)


def test_resolution_captures_scoped_comment_thread():
    # A resolution can carry its own comment THREAD (same card markup as ticket
    # comments). Capture it scoped to div.resolution-container — a comment card
    # OUTSIDE the container (a main ticket comment) must NOT be pulled in.
    synthetic = """
    <html><body>
      <div class="rounded-lg border bg-white">
        <span class="hidden">comment 111 posted by </span><a class="text-blue-600">Outsider</a>
        <div class="comment-html-content"><p>main ticket comment</p></div>
      </div>
      <div class="resolution-container">
        <div class="post-content"><p>Fixed it.</p></div>
        <div class="rounded-lg border bg-white">
          <span class="hidden">comment 222 posted by </span><a class="text-blue-600">Resolver</a>
          <div class="comment-html-content"><p>resolution reply</p></div>
        </div>
      </div>
    </body></html>
    """
    r = parse_resolution(synthetic)
    assert [c["author"] for c in r["comments"]] == ["Resolver"]
    assert "resolution reply" in r["comments"][0]["body"]


# ── parse_files ───────────────────────────────────────────────────────────────

def test_files_count():
    files = parse_files(FILES_HTML)
    assert len(files) == 2


def test_files_labels_non_empty():
    files = parse_files(FILES_HTML)
    for f in files:
        assert f["label"], "a file entry has an empty label"


def test_files_targets_icon_downloads_not_comment_buttons():
    # The Files sub-view ALSO renders the comment list (with text "Download" buttons).
    # parse_files must capture ONLY the panel's icon downloads (button title="Download",
    # whose value the portal wraps in literal quotes) — never the comment text-Download
    # buttons, or comment files get double-counted.
    synthetic = """
    <html><body>
      <div class="files-panel">
        <div class="p-3 border rounded-lg">
          <div class="min-w-0"><p class="text-sm break-words">export.csv</p></div>
          <button class="p-1.5" title='\"Download\"'></button>
        </div>
      </div>
      <div class="space-y-2 sm:space-y-4">
        <div class="p-2 rounded-lg border bg-white">
          <div class="comment-html-content"><p>see file</p></div>
          <button class="inline-flex">Download</button>
        </div>
      </div>
    </body></html>
    """
    files = parse_files(synthetic)
    assert len(files) == 1
    assert files[0]["label"] == "export.csv"


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
