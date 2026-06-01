import pytest
from scraper.parsers.article import parse_article


def _parse(body_html: str) -> str:
    html = f"<html><body><div id='main-content'>{body_html}</div></body></html>"
    result = parse_article(
        html, "SA", "System Administration", "tradedesk",
        "Test Article", "https://help.contoso.example/display/SA/Test", "/tmp/shot.png",
    )
    return result["body_md"]


def test_parse_article_returns_required_fields():
    result = parse_article(
        "<html><body><div id='main-content'><p>Hi</p></div></body></html>",
        "SA", "System Administration", "tradedesk",
        "Test", "https://x.com", "/tmp/x.png",
    )
    for key in ("space_key", "space_name", "product", "title", "url", "scraped_at", "screenshot", "body_md"):
        assert key in result
    assert result["space_key"] == "SA"
    assert result["product"] == "tradedesk"


def test_h2_becomes_markdown_heading():
    md = _parse("<h2>Instructions</h2>")
    assert "## Instructions" in md


def test_h3_becomes_level_3_heading():
    md = _parse("<h3>Sub Section</h3>")
    assert "### Sub Section" in md


def test_paragraph_text_preserved():
    md = _parse("<p>Configure the email service.</p>")
    assert "Configure the email service." in md


def test_ordered_list():
    md = _parse("<ol><li>First step</li><li>Second step</li></ol>")
    assert "1. First step" in md
    assert "2. Second step" in md


def test_unordered_list():
    md = _parse("<ul><li>Item A</li><li>Item B</li></ul>")
    assert "- Item A" in md
    assert "- Item B" in md


def test_table_becomes_markdown_table():
    html = "<table><tr><th>Name</th><th>Value</th></tr><tr><td>Alpha</td><td>1</td></tr></table>"
    md = _parse(html)
    assert "| Name |" in md
    assert "| Alpha |" in md
    assert "| --- |" in md


def test_code_block():
    md = _parse("<pre><code>SELECT * FROM table;</code></pre>")
    assert "```" in md
    assert "SELECT * FROM table;" in md


def test_inline_code():
    md = _parse("<p>Use the <code>config</code> setting.</p>")
    assert "`config`" in md


def test_bold_text():
    md = _parse("<p><strong>Important:</strong> read this.</p>")
    assert "**Important:**" in md


def test_confluence_note_panel():
    html = """<div class="confluence-information-macro confluence-information-macro-note">
        <div class="confluence-information-macro-body"><p>Remember to save.</p></div>
    </div>"""
    md = _parse(html)
    assert "> **Note:**" in md
    assert "Remember to save." in md


def test_confluence_warning_panel():
    html = """<div class="confluence-information-macro confluence-information-macro-warning">
        <div class="confluence-information-macro-body"><p>Do not delete.</p></div>
    </div>"""
    md = _parse(html)
    assert "> **Warning:**" in md


def test_toc_macro_excluded():
    html = "<div class='toc-macro'>Contents</div><h2>Real Heading</h2>"
    md = _parse(html)
    assert "Contents" not in md
    assert "## Real Heading" in md


def test_image_becomes_markdown_image():
    html = "<img src='/download/attachments/123/img.png' alt='screenshot'/>"
    md = _parse(html)
    assert "![screenshot](" in md
    assert "img.png" in md


def test_image_src_made_absolute():
    html = "<img src='/download/attachments/123/img.png' alt='x'/>"
    md = _parse(html)
    assert "https://help.contoso.example" in md
