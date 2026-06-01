# KB Full-Site Scraper (v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "v2 — Knowledge Base" tab to the existing Contoso KB Scraper GUI that scrapes all 34 Confluence spaces on help.contoso.example, saving each article as JSON + Markdown under `library/kb/`.

**Architecture:** Reuse `Browser`, `StateTracker`, `EngineCallbacks`, `CancellationToken` from the existing scraper unchanged. Add `KBEngine` that enumerates pages via Confluence REST API (`/rest/api/content`), renders them with the existing Playwright `Browser`, and converts HTML to Markdown using a new article parser. The GUI's `MainWindow` is refactored to use `QTabWidget`: Tab 1 = v1 (release notes), Tab 2 = v2 (`KBTab` widget). Each tab is fully self-contained with its own controls and state.

**Tech Stack:** Python 3.x, Playwright (sync), BeautifulSoup4/lxml, PySide6, pytest

**Spec:** `docs/superpowers/specs/2026-06-01-kb-full-site-scraper-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `scraper/kb_config.py` | All 34 space definitions + KB path constants |
| Create | `scraper/kb_discovery.py` | `discover_articles()` — enumerate pages via REST API |
| Create | `scraper/parsers/article.py` | HTML → Markdown body converter |
| Create | `scraper/writers/article_writer.py` | Save article JSON + Markdown to disk |
| Create | `scraper/writers/kb_index_generator.py` | Build `index.json` + `index.md` from library |
| Create | `scraper/kb_engine.py` | v2 scrape orchestration (mirrors `engine.py`) |
| Create | `scraper/kb_tab.py` | `KBSpaceCard` + `KBTab(QWidget)` for Tab 2 |
| Modify | `scraper/gui.py` | Wrap UI in `QTabWidget`; move v1 toolbar to inline buttons |
| Create | `tests/__init__.py` | Empty, makes tests/ a package |
| Create | `tests/test_kb_discovery.py` | Unit tests for discovery |
| Create | `tests/test_article_parser.py` | Unit tests for HTML→Markdown parser |
| Create | `tests/test_article_writer.py` | Unit tests for file writing |
| Create | `tests/test_kb_index.py` | Unit tests for index generation |

---

## Task 0: Test Infrastructure

**Files:**
- Create: `tests/__init__.py`

- [ ] **Step 1: Install pytest into the existing venv**

```powershell
scraper\venv\Scripts\python.exe -m pip install pytest
```

Expected output: `Successfully installed pytest-...`

- [ ] **Step 2: Create tests package**

Create `tests/__init__.py` as an empty file.

- [ ] **Step 3: Verify pytest runs**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: `no tests ran` (0 collected, no errors)

- [ ] **Step 4: Commit**

```powershell
git add tests/__init__.py
git commit -m "chore: add pytest test infrastructure"
```

---

## Task 1: kb_config.py

**Files:**
- Create: `scraper/kb_config.py`

- [ ] **Step 1: Create `scraper/kb_config.py`**

```python
# scraper/kb_config.py
from pathlib import Path
from scraper.config import STATE_DIR, LIBRARY_BASE

KB_SPACES: list[dict] = [
    # TradeDesk KB
    {"space_key": "SA",          "display_name": "System Administration", "product": "tradedesk", "product_label": "TradeDesk KB", "lib_folder": "system_administration"},
    {"space_key": "parameters",  "display_name": "Parameters",            "product": "tradedesk", "product_label": "TradeDesk KB", "lib_folder": "parameters"},
    {"space_key": "Finance",     "display_name": "Finance",               "product": "tradedesk", "product_label": "TradeDesk KB", "lib_folder": "finance"},
    {"space_key": "Dealing",     "display_name": "Dealing",               "product": "tradedesk", "product_label": "TradeDesk KB", "lib_folder": "dealing"},
    {"space_key": "compliance",  "display_name": "Compliance",            "product": "tradedesk", "product_label": "TradeDesk KB", "lib_folder": "compliance"},
    {"space_key": "Reports",     "display_name": "Reports",               "product": "tradedesk", "product_label": "TradeDesk KB", "lib_folder": "reports"},
    # Web 2.0 KB
    {"space_key": "administration", "display_name": "Administration",   "product": "web2", "product_label": "Web 2.0 KB", "lib_folder": "administration"},
    {"space_key": "beneficiaries",  "display_name": "Beneficiaries",    "product": "web2", "product_label": "Web 2.0 KB", "lib_folder": "beneficiaries"},
    {"space_key": "BookingDeals",   "display_name": "Booking Deals",    "product": "web2", "product_label": "Web 2.0 KB", "lib_folder": "booking_deals"},
    {"space_key": "dealinghistory", "display_name": "Dealing History",  "product": "web2", "product_label": "Web 2.0 KB", "lib_folder": "dealing_history"},
    {"space_key": "documents",      "display_name": "Documents",        "product": "web2", "product_label": "Web 2.0 KB", "lib_folder": "documents"},
    {"space_key": "GettingStarted", "display_name": "Getting Started",  "product": "web2", "product_label": "Web 2.0 KB", "lib_folder": "getting_started"},
    {"space_key": "howto",          "display_name": "How To's",         "product": "web2", "product_label": "Web 2.0 KB", "lib_folder": "how_to"},
    {"space_key": "MyAccount",      "display_name": "My Account",       "product": "web2", "product_label": "Web 2.0 KB", "lib_folder": "my_account"},
    {"space_key": "payments",       "display_name": "Payments",         "product": "web2", "product_label": "Web 2.0 KB", "lib_folder": "payments"},
    # Web 4.0 KB
    {"space_key": "BookingDealsWeb4",   "display_name": "Booking Deals",   "product": "web4", "product_label": "Web 4.0 KB", "lib_folder": "booking_deals"},
    {"space_key": "DealingHistoryWeb4", "display_name": "Dealing History", "product": "web4", "product_label": "Web 4.0 KB", "lib_folder": "dealing_history"},
    {"space_key": "MyAccountWeb4",      "display_name": "My Account",      "product": "web4", "product_label": "Web 4.0 KB", "lib_folder": "my_account"},
    {"space_key": "PaymentsWeb4",       "display_name": "Payments",        "product": "web4", "product_label": "Web 4.0 KB", "lib_folder": "payments"},
    {"space_key": "RecipientsWeb4",     "display_name": "Recipients",      "product": "web4", "product_label": "Web 4.0 KB", "lib_folder": "recipients"},
    # API KB
    {"space_key": "Functions",           "display_name": "API Functions",         "product": "api", "product_label": "API KB", "lib_folder": "functions"},
    {"space_key": "GS",                  "display_name": "Getting Started",       "product": "api", "product_label": "API KB", "lib_folder": "getting_started"},
    {"space_key": "API25ReleaseNotes",   "display_name": "API 2.5 Release Notes", "product": "api", "product_label": "API KB", "lib_folder": "api_25_release_notes"},
    {"space_key": "apireleasenotes",     "display_name": "Release Notes",         "product": "api", "product_label": "API KB", "lib_folder": "release_notes"},
    {"space_key": "RestAPIReleaseNotes", "display_name": "REST API Release Notes","product": "api", "product_label": "API KB", "lib_folder": "rest_api_release_notes"},
    # SalesHub KB
    {"space_key": "SHGettingStarted",   "display_name": "Getting Started",           "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "getting_started"},
    {"space_key": "SFFormManagement",    "display_name": "Form Management",            "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "form_management"},
    {"space_key": "SFHowTo",             "display_name": "How To's",                   "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "how_to"},
    {"space_key": "SFOpenForms",         "display_name": "Open Form",                  "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "open_form"},
    {"space_key": "SFUserAccessControl", "display_name": "User Access Control",        "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "user_access_control"},
    {"space_key": "SHAPIReleaseNotes",  "display_name": "SalesHub API Release Notes",  "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "sh_api_release_notes"},
    {"space_key": "SFReleaseNotes",      "display_name": "Release Notes",              "product": "saleshub", "product_label": "SalesHub KB", "lib_folder": "release_notes"},
    # Other
    {"space_key": "FBD",            "display_name": "Form Builder Docs", "product": "other", "product_label": "Other", "lib_folder": "form_builder_docs"},
    {"space_key": "WebReleaseNotes","display_name": "Web Release Notes", "product": "other", "product_label": "Other", "lib_folder": "web_release_notes"},
]

KB_SPACES_BY_KEY: dict[str, dict] = {s["space_key"]: s for s in KB_SPACES}

KB_PRODUCT_GROUPS: dict[str, list[dict]] = {}
for _s in KB_SPACES:
    KB_PRODUCT_GROUPS.setdefault(_s["product_label"], []).append(_s)

KB_ARTICLES_STATE_FILE: Path = STATE_DIR / "scraped_articles.json"
KB_LIBRARY_BASE: Path = LIBRARY_BASE / "kb"
```

- [ ] **Step 2: Verify import works**

```powershell
scraper\venv\Scripts\python.exe -c "from scraper.kb_config import KB_SPACES, KB_SPACES_BY_KEY, KB_PRODUCT_GROUPS; print(len(KB_SPACES), 'spaces loaded')"
```

Expected: `34 spaces loaded`

- [ ] **Step 3: Commit**

```powershell
git add scraper/kb_config.py
git commit -m "feat: add kb_config with 34 Confluence space definitions"
```

---

## Task 2: kb_discovery.py

**Files:**
- Create: `scraper/kb_discovery.py`
- Create: `tests/test_kb_discovery.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_kb_discovery.py`:

```python
import pytest
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
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_kb_discovery.py -v
```

Expected: `ImportError` — `scraper.kb_discovery` does not exist yet.

- [ ] **Step 3: Create `scraper/kb_discovery.py`**

```python
# scraper/kb_discovery.py
from __future__ import annotations
import re
from typing import Callable

from scraper.config import BASE_URL
from scraper.discovery import default_http_get


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug[:120] or "untitled"


def discover_articles(
    space_key: str,
    http_get: Callable[[str], dict] = default_http_get,
) -> list[dict]:
    """Return all pages in a Confluence space as article descriptors.

    Returns list of dicts: {"title", "url", "page_id", "slug"}
    Follows _links.next pagination until exhausted. Deduplicates by URL.
    """
    results: list[dict] = []
    seen_urls: set[str] = set()
    next_path: str | None = (
        f"/rest/api/content?spaceKey={space_key}&type=page&limit=100&start=0"
    )

    while next_path:
        url = next_path if next_path.startswith("http") else f"{BASE_URL}{next_path}"
        data = http_get(url)
        for item in data.get("results", []):
            title = item.get("title", "")
            webui = (item.get("_links") or {}).get("webui", "")
            full_url = webui if webui.startswith("http") else f"{BASE_URL}{webui}"
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            results.append({
                "title": title,
                "url": full_url,
                "page_id": str(item.get("id", "")),
                "slug": _slugify(title),
            })
        next_path = (data.get("_links") or {}).get("next")

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_kb_discovery.py -v
```

Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add scraper/kb_discovery.py tests/test_kb_discovery.py
git commit -m "feat: add kb_discovery with article enumeration via REST API"
```

---

## Task 3: parsers/article.py

**Files:**
- Create: `scraper/parsers/article.py`
- Create: `tests/test_article_parser.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_article_parser.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_article_parser.py -v
```

Expected: `ImportError` — `scraper.parsers.article` does not exist yet.

- [ ] **Step 3: Create `scraper/parsers/article.py`**

```python
# scraper/parsers/article.py
from __future__ import annotations
from datetime import datetime
from bs4 import BeautifulSoup, Tag, NavigableString

from scraper.parsers.universal import _find_content, _collapse_ws
from scraper.config import BASE_URL


def _abs_url(src: str) -> str:
    return src if src.startswith("http") else f"{BASE_URL}{src}"


def _inline_content(el: Tag) -> str:
    """Extract inline-formatted text from an element."""
    parts: list[str] = []
    for child in el.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif child.name in ("strong", "b"):
            t = child.get_text()
            parts.append(f"**{t}**" if t.strip() else t)
        elif child.name in ("em", "i"):
            t = child.get_text()
            parts.append(f"*{t}*" if t.strip() else t)
        elif child.name == "code":
            parts.append(f"`{child.get_text()}`")
        elif child.name == "a":
            text = _collapse_ws(child.get_text())
            href = child.get("href", "")
            parts.append(f"[{text}]({href})" if href and not href.startswith("#") else text)
        elif child.name == "img":
            alt = child.get("alt", "image")
            src = child.get("src", "")
            parts.append(f"![{alt}]({_abs_url(src)})" if src else "")
        elif child.name == "br":
            parts.append("\n")
        elif hasattr(child, "children"):
            parts.append(_inline_content(child))
        else:
            parts.append(str(child))
    return _collapse_ws("".join(parts))


def _table_to_md(table: Tag) -> str:
    """Convert HTML table to Markdown table."""
    rows = table.find_all("tr")
    if not rows:
        return ""
    headers = [_collapse_ws(c.get_text(separator=" ", strip=True))
               for c in rows[0].find_all(["th", "td"])]
    if not headers:
        return ""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        vals = [_collapse_ws(c.get_text(separator=" ", strip=True)) for c in cells]
        while len(vals) < len(headers):
            vals.append("")
        lines.append("| " + " | ".join(vals[: len(headers)]) + " |")
    return "\n".join(lines)


def _element_to_md(el: Tag, list_depth: int = 0) -> str:
    """Recursively convert a BeautifulSoup element to a Markdown string."""
    if isinstance(el, NavigableString):
        return str(el).strip()

    name = el.name
    if not name or name in ("script", "style"):
        return ""

    classes: list[str] = el.get("class") or []

    # Skip table-of-contents macros
    if "toc-macro" in classes:
        return ""
    if name == "div" and el.get("data-macro-name") == "toc":
        return ""

    # Headings
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        text = _collapse_ws(el.get_text(separator=" ", strip=True))
        return f"\n{'#' * int(name[1])} {text}\n" if text else ""

    # Paragraphs
    if name == "p":
        text = _inline_content(el)
        return f"\n{text}\n" if text.strip() else ""

    # Ordered / unordered lists
    if name in ("ul", "ol"):
        parts: list[str] = []
        counter = 0
        for child in el.children:
            if not isinstance(child, Tag) or child.name != "li":
                continue
            counter += 1
            prefix = f"{counter}." if name == "ol" else "-"
            indent = "  " * list_depth
            direct: list[str] = []
            nested = ""
            for li_child in child.children:
                if isinstance(li_child, NavigableString):
                    direct.append(str(li_child))
                elif li_child.name in ("ul", "ol"):
                    nested += "\n" + _element_to_md(li_child, list_depth + 1)
                else:
                    direct.append(_inline_content(li_child))
            item_text = _collapse_ws("".join(direct))
            parts.append(f"{indent}{prefix} {item_text}{nested}")
        return "\n" + "\n".join(parts) + "\n"

    # Tables
    if name == "table":
        return "\n" + _table_to_md(el) + "\n"

    # Code blocks
    if name == "pre":
        code_el = el.find("code")
        code = code_el.get_text() if code_el else el.get_text()
        return f"\n```\n{code}\n```\n"

    if name == "code" and (not el.parent or el.parent.name != "pre"):
        return f"`{el.get_text()}`"

    # Images
    if name == "img":
        alt = el.get("alt", "image")
        src = el.get("src", "")
        return f"![{alt}]({_abs_url(src)})" if src else ""

    # Confluence info / note / warning / tip panels
    if "confluence-information-macro" in classes:
        body_div = el.find("div", class_="confluence-information-macro-body")
        note_text = _inline_content(body_div) if body_div else el.get_text(strip=True)
        note_type = "Note"
        for cls in classes:
            if "warning" in cls:
                note_type = "Warning"
                break
            if "tip" in cls:
                note_type = "Tip"
                break
        return f"\n> **{note_type}:** {note_text}\n"

    # Confluence expand macro — render contents
    if "expand-container" in classes or el.get("data-macro-name") == "expand":
        body = el.find("div", class_="expand-content") or el
        inner = [_element_to_md(c, list_depth) for c in body.children if isinstance(c, Tag)]
        return "\n".join(p for p in inner if p.strip())

    # Blockquote
    if name == "blockquote":
        inner_parts = [_element_to_md(c, list_depth) for c in el.children if isinstance(c, Tag)]
        inner = "\n".join(p for p in inner_parts if p.strip())
        return "\n" + "\n".join(f"> {line}" for line in inner.splitlines()) + "\n"

    # Generic container — recurse
    child_parts: list[str] = []
    for child in el.children:
        if isinstance(child, NavigableString):
            t = str(child).strip()
            if t:
                child_parts.append(t)
        elif isinstance(child, Tag):
            md = _element_to_md(child, list_depth)
            if md.strip():
                child_parts.append(md)

    sep = " " if name in ("span", "td", "th") else "\n"
    return sep.join(child_parts)


def parse_article(
    html: str,
    space_key: str,
    space_name: str,
    product: str,
    title: str,
    url: str,
    screenshot_path: str,
) -> dict:
    """Parse a rendered Confluence page HTML into an article data dict.

    Returns:
        dict with keys: space_key, space_name, product, title, url,
                        scraped_at, screenshot, body_md
    """
    soup = BeautifulSoup(html, "lxml")

    for sel in (".toc-macro", "[data-macro-name='toc']", "#breadcrumbs", ".page-metadata"):
        for node in soup.select(sel):
            node.decompose()

    content = _find_content(soup)

    parts: list[str] = []
    for child in content.children:
        if isinstance(child, NavigableString):
            t = str(child).strip()
            if t:
                parts.append(t)
        elif isinstance(child, Tag):
            md = _element_to_md(child)
            if md.strip():
                parts.append(md.strip())

    return {
        "space_key": space_key,
        "space_name": space_name,
        "product": product,
        "title": title,
        "url": url,
        "scraped_at": datetime.now().isoformat(),
        "screenshot": screenshot_path,
        "body_md": "\n\n".join(parts),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_article_parser.py -v
```

Expected: all 15 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add scraper/parsers/article.py tests/test_article_parser.py
git commit -m "feat: add article HTML-to-Markdown parser"
```

---

## Task 4: writers/article_writer.py

**Files:**
- Create: `scraper/writers/article_writer.py`
- Create: `tests/test_article_writer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_article_writer.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_article_writer.py -v
```

Expected: `ImportError` — `scraper.writers.article_writer` does not exist yet.

- [ ] **Step 3: Create `scraper/writers/article_writer.py`**

```python
# scraper/writers/article_writer.py
from __future__ import annotations
import json
import re
from pathlib import Path


def safe_slug(text: str) -> str:
    """Convert article title to a filesystem-safe slug, max 120 chars."""
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug[:120] or "untitled"


def save_article(data: dict, kb_library_base: Path, space_cfg: dict) -> None:
    """Save article data as .json and .md files.

    Writes to:
      kb_library_base / space_cfg["product"] / space_cfg["lib_folder"] / {slug}.{json|md}
    """
    article_dir = kb_library_base / space_cfg["product"] / space_cfg["lib_folder"]
    article_dir.mkdir(parents=True, exist_ok=True)

    slug = safe_slug(data["title"])

    (article_dir / f"{slug}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    frontmatter = (
        "---\n"
        f"title: {data['title']}\n"
        f"space: {data['space_name']}\n"
        f"product: {data['product']}\n"
        f"url: {data['url']}\n"
        f"scraped_at: {data['scraped_at']}\n"
        "---\n\n"
    )
    (article_dir / f"{slug}.md").write_text(
        frontmatter + data["body_md"], encoding="utf-8"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_article_writer.py -v
```

Expected: all 9 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add scraper/writers/article_writer.py tests/test_article_writer.py
git commit -m "feat: add article_writer saving JSON + Markdown with YAML frontmatter"
```

---

## Task 5: writers/kb_index_generator.py

**Files:**
- Create: `scraper/writers/kb_index_generator.py`
- Create: `tests/test_kb_index.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_kb_index.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_kb_index.py -v
```

Expected: `ImportError` — `scraper.writers.kb_index_generator` does not exist yet.

- [ ] **Step 3: Create `scraper/writers/kb_index_generator.py`**

```python
# scraper/writers/kb_index_generator.py
from __future__ import annotations
import json
from pathlib import Path

_PRODUCT_ORDER = ["tradedesk", "web2", "web4", "api", "saleshub", "other"]
_PRODUCT_LABELS = {
    "tradedesk": "TradeDesk KB",
    "web2": "Web 2.0 KB",
    "web4": "Web 4.0 KB",
    "api": "API KB",
    "saleshub": "SalesHub KB",
    "other": "Other",
}


def generate_kb_index(kb_library_base: Path, spaces: list[dict]) -> None:
    """Build index.json and index.md from all .json article files in kb_library_base."""
    articles: list[dict] = []

    for json_file in sorted(kb_library_base.rglob("*.json")):
        if json_file.name == "index.json":
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            articles.append({
                "title":      data.get("title", ""),
                "space_key":  data.get("space_key", ""),
                "space_name": data.get("space_name", ""),
                "product":    data.get("product", ""),
                "url":        data.get("url", ""),
                "scraped_at": data.get("scraped_at", ""),
            })
        except Exception:
            continue

    (kb_library_base / "index.json").write_text(
        json.dumps({"total": len(articles), "articles": articles}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    by_product: dict[str, list[dict]] = {}
    for art in articles:
        by_product.setdefault(art["product"], []).append(art)

    lines = [f"# Contoso Knowledge Base Index\n\n**Total articles:** {len(articles)}\n"]
    for product in _PRODUCT_ORDER:
        if product not in by_product:
            continue
        label = _PRODUCT_LABELS.get(product, product)
        lines.append(f"\n## {label}\n")
        lines.append("| Title | Space | URL |")
        lines.append("|---|---|---|")
        for art in sorted(by_product[product], key=lambda a: (a["space_name"], a["title"])):
            title = art["title"].replace("|", "\\|")
            space = art["space_name"].replace("|", "\\|")
            lines.append(f"| {title} | {space} | {art['url']} |")

    (kb_library_base / "index.md").write_text("\n".join(lines), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_kb_index.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Run all tests to confirm no regressions**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add scraper/writers/kb_index_generator.py tests/test_kb_index.py
git commit -m "feat: add kb_index_generator building index.json and index.md"
```

---

## Task 6: kb_engine.py

**Files:**
- Create: `scraper/kb_engine.py`

No automated tests for the engine — it requires a live browser and network. Verified manually in Task 8 by running the GUI.

- [ ] **Step 1: Create `scraper/kb_engine.py`**

```python
# scraper/kb_engine.py
from __future__ import annotations
import json
import logging
from pathlib import Path

from scraper.kb_config import (
    KB_SPACES, KB_SPACES_BY_KEY, KB_ARTICLES_STATE_FILE, KB_LIBRARY_BASE,
)
from scraper.config import REPORT_FILE
from scraper.core import Browser, StateTracker
from scraper.engine import EngineCallbacks, CancellationToken
from scraper.kb_discovery import discover_articles
from scraper.parsers.article import parse_article
from scraper.writers.article_writer import save_article, safe_slug
from scraper.writers.kb_index_generator import generate_kb_index

log = logging.getLogger("scraper")

KB_REPORT_FILE = REPORT_FILE.parent / "last_kb_run_report.json"


class KBEngine:
    def __init__(
        self,
        callbacks: EngineCallbacks | None = None,
        cancel_token: CancellationToken | None = None,
    ):
        self.cb = callbacks or EngineCallbacks()
        self.cancel = cancel_token or CancellationToken()

    def validate(self) -> bool:
        self.cb.on_started("validate_kb")
        self.cb.on_log("info", "Validating KB spaces (dry-run, no scraping)...")
        ok = True
        report: dict = {}
        for cfg in KB_SPACES:
            key = cfg["space_key"]
            try:
                items = discover_articles(key)
                count = len(items)
                self.cb.on_log("info", f"  {key} [{cfg['display_name']}]: {count} articles")
                report[key] = {"display_name": cfg["display_name"], "count": count}
                if not items:
                    ok = False
            except Exception as exc:
                ok = False
                self.cb.on_log("error", f"  {key}: ERROR {exc}")
                report[key] = {"display_name": cfg["display_name"], "error": str(exc)}
        self.cb.on_log("info", f"KB Validation {'PASSED' if ok else 'FAILED'}")
        self.cb.on_finished("validate_kb", report)
        return ok

    def rebuild_indexes(self) -> None:
        self.cb.on_started("rebuild_kb_indexes")
        self.cb.on_log("info", "Rebuilding KB indexes...")
        generate_kb_index(KB_LIBRARY_BASE, KB_SPACES)
        self.cb.on_log("info", f"KB indexes written to {KB_LIBRARY_BASE}")
        self.cb.on_finished("rebuild_kb_indexes", {})

    def scrape_space(self, space_key: str, force: bool = False) -> dict:
        return self._scrape_one(
            space_key, force,
            with_index_rebuild=True,
            action_label=f"scrape_kb_{space_key}",
        )

    def scrape_all(self, force: bool = False) -> dict:
        self.cb.on_started("scrape_kb_all")
        report: dict = {}
        for cfg in KB_SPACES:
            if self.cancel.is_cancelled():
                self.cb.on_log("warning", "Cancelled — stopping scrape_kb_all")
                break
            stats = self._scrape_one(
                cfg["space_key"], force, with_index_rebuild=False, action_label=None
            )
            report[cfg["space_key"]] = stats
        try:
            self.rebuild_indexes()
        except Exception as exc:
            self.cb.on_log("error", f"KB index rebuild failed: {exc}")
        self._write_report(report)
        self.cb.on_finished("scrape_kb_all", report)
        return report

    def _scrape_one(
        self, space_key: str, force: bool,
        with_index_rebuild: bool, action_label: str | None,
    ) -> dict:
        if action_label:
            self.cb.on_started(action_label)

        cfg = KB_SPACES_BY_KEY[space_key]
        tracker = StateTracker(KB_ARTICLES_STATE_FILE)
        self.cb.on_log("info", f"=== {cfg['display_name']} ({space_key}) ===")

        try:
            articles = discover_articles(space_key)
        except Exception as exc:
            self.cb.on_log("error", f"{space_key}: discovery failed: {exc}")
            stats = {"discovered": 0, "new": 0, "skipped": 0, "failed": 0, "failed_urls": []}
            self.cb.on_status(space_key, stats)
            if action_label:
                self.cb.on_finished(action_label, stats)
            return stats

        self.cb.on_log("info", f"{space_key}: {len(articles)} article(s) discovered")
        stats = {
            "discovered": len(articles), "new": 0,
            "skipped": 0, "failed": 0, "failed_urls": [],
        }
        self.cb.on_status(space_key, stats)

        total = len(articles)
        screenshot_dir = KB_LIBRARY_BASE / cfg["product"] / cfg["lib_folder"] / "screenshots"

        with Browser() as browser:
            for idx, art in enumerate(articles, start=1):
                if self.cancel.is_cancelled():
                    self.cb.on_log("warning", f"{space_key}: cancelled before '{art['title']}'")
                    break

                title, url, slug = art["title"], art["url"], art["slug"]
                self.cb.on_progress(space_key, title, idx, total)

                if not force and tracker.is_scraped(space_key, slug):
                    stats["skipped"] += 1
                    self.cb.on_status(space_key, stats)
                    continue

                try:
                    browser.navigate(url)
                    browser.expand_confluence_macros()
                    shot = str(screenshot_dir / f"{slug}.png")
                    browser.screenshot(shot)
                    data = parse_article(
                        browser.get_content(),
                        space_key=space_key,
                        space_name=cfg["display_name"],
                        product=cfg["product"],
                        title=title,
                        url=url,
                        screenshot_path=shot,
                    )
                    save_article(data, KB_LIBRARY_BASE, cfg)
                    tracker.mark_scraped(space_key, slug, url)
                    stats["new"] += 1
                    self.cb.on_log("info", f"[OK] {title}")
                except Exception as exc:
                    stats["failed"] += 1
                    stats["failed_urls"].append(url)
                    self.cb.on_log("error", f"[FAIL] {title}: {exc}")
                self.cb.on_status(space_key, stats)

        self.cb.on_log(
            "info",
            f"{space_key} done: new={stats['new']} skipped={stats['skipped']} failed={stats['failed']}",
        )
        if with_index_rebuild:
            try:
                self.rebuild_indexes()
            except Exception as exc:
                self.cb.on_log("error", f"KB index rebuild failed: {exc}")
            self._write_report({space_key: stats})
        if action_label:
            self.cb.on_finished(action_label, stats)
        return stats

    def _write_report(self, report: dict) -> None:
        KB_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        KB_REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self.cb.on_log("info", f"KB run report written to {KB_REPORT_FILE}")
```

- [ ] **Step 2: Verify import is clean**

```powershell
scraper\venv\Scripts\python.exe -c "from scraper.kb_engine import KBEngine; print('KBEngine OK')"
```

Expected: `KBEngine OK`

- [ ] **Step 3: Run all tests to confirm nothing broken**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit**

```powershell
git add scraper/kb_engine.py
git commit -m "feat: add KBEngine orchestrating v2 full-site scrape"
```

---

## Task 7: kb_tab.py

**Files:**
- Create: `scraper/kb_tab.py`

No automated tests — GUI widgets require a display. Verified visually in Task 8.

- [ ] **Step 1: Create `scraper/kb_tab.py`**

```python
# scraper/kb_tab.py
from __future__ import annotations
import logging
from datetime import datetime

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QTextCursor, QFont, QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QPlainTextEdit, QProgressBar, QFrame, QScrollArea, QGroupBox,
)

from scraper.kb_config import KB_PRODUCT_GROUPS
from scraper.kb_engine import KBEngine
from scraper.engine import EngineCallbacks, CancellationToken


class _SignalBridge(QObject):
    log_sig      = Signal(str, str)
    status_sig   = Signal(str, dict)
    progress_sig = Signal(str, str, int, int)
    started_sig  = Signal(str)
    finished_sig = Signal(str, dict)


class _BridgeCallbacks(EngineCallbacks):
    def __init__(self, bridge: _SignalBridge):
        self.bridge = bridge
    def on_log(self, level, msg):                  self.bridge.log_sig.emit(level, msg)
    def on_status(self, key, stats):               self.bridge.status_sig.emit(key, dict(stats))
    def on_progress(self, key, title, i, n):       self.bridge.progress_sig.emit(key, title, i, n)
    def on_started(self, action):                  self.bridge.started_sig.emit(action)
    def on_finished(self, action, report):         self.bridge.finished_sig.emit(action, dict(report))


class _Worker(QThread):
    def __init__(self, engine: KBEngine, action: str, kwargs: dict):
        super().__init__()
        self.engine = engine
        self.action = action
        self.kwargs = kwargs

    def run(self):
        try:
            getattr(self.engine, self.action)(**self.kwargs)
        except Exception as exc:
            logging.exception("KBWorker %s raised", self.action)
            self.engine.cb.on_log("error", f"{self.action} crashed: {exc}")


class KBSpaceCard(QFrame):
    """Status card for one Confluence space — mirrors v1 StatusCard."""

    def __init__(self, space_key: str, display_name: str, on_scrape):
        super().__init__()
        self.space_key = space_key
        self.setFrameShape(QFrame.StyledPanel)
        self.setFixedWidth(160)
        self.setMinimumHeight(115)

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 4)
        v.setSpacing(2)

        lbl = QLabel(f"<b>{display_name}</b>")
        lbl.setWordWrap(True)
        lbl.setStyleSheet("font-size: 11px;")
        v.addWidget(lbl)

        self.lbl_found   = QLabel("Found: —")
        self.lbl_new     = QLabel("New: 0")
        self.lbl_skipped = QLabel("Skip: 0")
        self.lbl_failed  = QLabel("Fail: 0")
        for w in (self.lbl_found, self.lbl_new, self.lbl_skipped, self.lbl_failed):
            w.setStyleSheet("font-size: 10px;")
            v.addWidget(w)
        self.lbl_failed.setStyleSheet("font-size: 10px; color: #c62828;")

        row = QHBoxLayout()
        self.btn_scrape = QPushButton("Scrape")
        self.btn_scrape.setFixedHeight(22)
        self.chk_force = QCheckBox("F")
        self.chk_force.setToolTip("Force re-scrape")
        self.btn_scrape.clicked.connect(
            lambda: on_scrape(self.space_key, self.chk_force.isChecked())
        )
        row.addWidget(self.btn_scrape)
        row.addWidget(self.chk_force)
        v.addLayout(row)

    def update_stats(self, stats: dict):
        self.lbl_found.setText(f"Found: {stats.get('discovered', '—')}")
        self.lbl_new.setText(f"New: {stats.get('new', 0)}")
        self.lbl_skipped.setText(f"Skip: {stats.get('skipped', 0)}")
        self.lbl_failed.setText(f"Fail: {stats.get('failed', 0)}")

    def set_enabled(self, enabled: bool):
        self.btn_scrape.setEnabled(enabled)
        self.chk_force.setEnabled(enabled)


class KBTab(QWidget):
    """v2 Knowledge Base scraper tab — self-contained, no shared state with v1."""

    MAX_LOG_LINES = 5000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bridge = _SignalBridge()
        self.cancel_token = CancellationToken()
        self.engine = KBEngine(
            callbacks=_BridgeCallbacks(self.bridge),
            cancel_token=self.cancel_token,
        )
        self.worker: _Worker | None = None
        self.cards: dict[str, KBSpaceCard] = {}
        self._build_ui()
        self._wire_signals()
        self._set_running(False)
        self._log("info", "v2 Knowledge Base Scraper ready.")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        # Top action buttons
        btn_row = QHBoxLayout()
        self.btn_validate = QPushButton("Validate")
        self.btn_indexes  = QPushButton("Rebuild Indexes")
        self.btn_stop     = QPushButton("⏹ STOP")
        for btn in (self.btn_validate, self.btn_indexes, self.btn_stop):
            btn_row.addWidget(btn)
        btn_row.addStretch()
        outer.addLayout(btn_row)

        # Scrollable space cards grouped by product family
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(300)
        container = QWidget()
        cards_layout = QVBoxLayout(container)
        cards_layout.setSpacing(8)

        for group_label, spaces in KB_PRODUCT_GROUPS.items():
            box = QGroupBox(group_label)
            row = QHBoxLayout(box)
            row.setSpacing(6)
            for cfg in spaces:
                card = KBSpaceCard(cfg["space_key"], cfg["display_name"], self._scrape_one)
                self.cards[cfg["space_key"]] = card
                row.addWidget(card)
            row.addStretch()
            cards_layout.addWidget(box)

        scroll.setWidget(container)
        outer.addWidget(scroll)

        # Progress bar
        self.lbl_progress = QLabel("Idle")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        outer.addWidget(self.lbl_progress)
        outer.addWidget(self.progress)

        # Bulk scrape buttons
        bulk = QHBoxLayout()
        self.btn_scrape_all = QPushButton("Scrape ALL (incremental)")
        self.btn_force_all  = QPushButton("Force re-scrape ALL")
        bulk.addWidget(self.btn_scrape_all)
        bulk.addWidget(self.btn_force_all)
        bulk.addStretch()
        outer.addLayout(bulk)

        # Log pane
        outer.addWidget(QLabel("<b>Log</b>"))
        self.log_pane = QPlainTextEdit()
        self.log_pane.setReadOnly(True)
        self.log_pane.setMaximumBlockCount(self.MAX_LOG_LINES)
        self.log_pane.setFont(QFont("Consolas", 9))
        outer.addWidget(self.log_pane, stretch=1)

    def _wire_signals(self):
        self.bridge.log_sig.connect(self._log)
        self.bridge.status_sig.connect(self._on_status)
        self.bridge.progress_sig.connect(self._on_progress)
        self.btn_validate.clicked.connect(lambda: self._start("validate"))
        self.btn_indexes.clicked.connect(lambda: self._start("rebuild_indexes"))
        self.btn_stop.clicked.connect(self._stop)
        self.btn_scrape_all.clicked.connect(lambda: self._start("scrape_all", {"force": False}))
        self.btn_force_all.clicked.connect(lambda: self._start("scrape_all", {"force": True}))

    # ── Actions ───────────────────────────────────────────────────────────────

    def _start(self, action: str, kwargs: dict | None = None):
        if self.worker and self.worker.isRunning():
            self._log("warning", "A KB run is already in progress.")
            return
        self.cancel_token = CancellationToken()
        self.engine.cancel = self.cancel_token
        self.worker = _Worker(self.engine, action, kwargs or {})
        self.worker.finished.connect(self._worker_done)
        self._set_running(True)
        self._log("info", f"--- Starting: {action} ---")
        self.worker.start()

    def _scrape_one(self, space_key: str, force: bool):
        self._start("scrape_space", {"space_key": space_key, "force": force})

    def _stop(self):
        if self.worker and self.worker.isRunning():
            self._log("warning", "Cancel requested — stopping after current article.")
            self.cancel_token.cancel()

    def _worker_done(self):
        self._set_running(False)
        self._log("info", "--- Run complete ---")
        self.lbl_progress.setText("Idle")
        self.progress.setValue(0)

    def _set_running(self, running: bool):
        for btn in (self.btn_validate, self.btn_indexes, self.btn_scrape_all, self.btn_force_all):
            btn.setEnabled(not running)
        for card in self.cards.values():
            card.set_enabled(not running)
        self.btn_stop.setEnabled(running)

    # ── Slots ─────────────────────────────────────────────────────────────────

    @Slot(str, str)
    def _log(self, level: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"{ts} {level.upper():7s} {msg}"
        cursor = self.log_pane.textCursor()
        fmt = QTextCharFormat()
        if level == "error":     fmt.setForeground(QColor("#c62828"))
        elif level == "warning": fmt.setForeground(QColor("#ef6c00"))
        else:                    fmt.setForeground(QColor("#212121"))
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(line + "\n", fmt)
        self.log_pane.setTextCursor(cursor)
        self.log_pane.ensureCursorVisible()
        getattr(logging, level if level in ("debug", "info", "warning", "error", "critical") else "info")(msg)

    @Slot(str, dict)
    def _on_status(self, space_key: str, stats: dict):
        card = self.cards.get(space_key)
        if card:
            card.update_stats(stats)

    @Slot(str, str, int, int)
    def _on_progress(self, space_key: str, title: str, idx: int, total: int):
        self.lbl_progress.setText(f"Scraping: {space_key} — {title}  ({idx}/{total})")
        self.progress.setValue(int(idx * 100 / total) if total else 0)
```

- [ ] **Step 2: Verify import is clean**

```powershell
scraper\venv\Scripts\python.exe -c "from scraper.kb_tab import KBTab, KBSpaceCard; print('KBTab OK')"
```

Expected: `KBTab OK`

- [ ] **Step 3: Commit**

```powershell
git add scraper/kb_tab.py
git commit -m "feat: add KBTab GUI widget with space cards grouped by product family"
```

---

## Task 8: gui.py — Add QTabWidget

**Files:**
- Modify: `scraper/gui.py`

This task refactors `MainWindow` to use `QTabWidget`. The existing v1 logic (callbacks, workers, engine) is **unchanged** — only the widget-building and signal-wiring methods are updated to use `QPushButton` rows instead of a window-level `QToolBar`.

- [ ] **Step 1: Read the current `scraper/gui.py` before editing**

Open `scraper/gui.py` and read it in full to confirm the current state matches what is described in this plan.

- [ ] **Step 2: Add `QTabWidget` and `QPushButton` to the imports**

Find this line in `gui.py`:
```python
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QPlainTextEdit, QProgressBar, QFrame,
    QToolBar, QStatusBar, QMessageBox,
)
```

Replace with:
```python
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QPlainTextEdit, QProgressBar, QFrame,
    QStatusBar, QMessageBox, QTabWidget,
)
```

(Remove `QToolBar`, add `QTabWidget`.)

- [ ] **Step 3: Add the `KBTab` import after existing scraper imports**

After the line `from scraper.config import PRODUCTS, LOG_FILE`, add:
```python
from scraper.kb_tab import KBTab
```

- [ ] **Step 4: Replace `_build_ui` with tabbed version**

Replace the entire `_build_ui` method with:

```python
def _build_ui(self):
    central = QWidget()
    self.setCentralWidget(central)
    outer = QVBoxLayout(central)
    outer.setContentsMargins(0, 0, 0, 0)

    self.tabs = QTabWidget()
    outer.addWidget(self.tabs)

    self.tabs.addTab(self._build_v1_widget(), "v1 — Release Notes")
    self.kb_tab = KBTab()
    self.tabs.addTab(self.kb_tab, "v2 — Knowledge Base")

    self.setStatusBar(QStatusBar())
    self.statusBar().showMessage(f"Log file: {LOG_FILE}")
```

- [ ] **Step 5: Add `_build_v1_widget` method**

Add this new method immediately after `_build_ui`:

```python
def _build_v1_widget(self) -> QWidget:
    w = QWidget()
    outer = QVBoxLayout(w)

    btn_row = QHBoxLayout()
    self.btn_validate = QPushButton("Validate")
    self.btn_discover = QPushButton("Discover / Refresh URLs")
    self.btn_indexes  = QPushButton("Rebuild Indexes")
    self.btn_stop     = QPushButton("⏹ STOP")
    for btn in (self.btn_validate, self.btn_discover, self.btn_indexes, self.btn_stop):
        btn_row.addWidget(btn)
    btn_row.addStretch()
    outer.addLayout(btn_row)

    cards_row = QHBoxLayout()
    self.cards: dict[str, StatusCard] = {}
    for key, cfg in PRODUCTS.items():
        card = StatusCard(key, cfg["display_name"], on_scrape=self._scrape_one)
        self.cards[key] = card
        cards_row.addWidget(card)
    outer.addLayout(cards_row)

    self.lbl_progress = QLabel("Idle")
    self.progress = QProgressBar()
    self.progress.setRange(0, 100)
    self.progress.setValue(0)
    outer.addWidget(self.lbl_progress)
    outer.addWidget(self.progress)

    bulk = QHBoxLayout()
    self.btn_scrape_all = QPushButton("Scrape ALL (incremental)")
    self.btn_force_all  = QPushButton("Force re-scrape ALL")
    bulk.addWidget(self.btn_scrape_all)
    bulk.addWidget(self.btn_force_all)
    bulk.addStretch()
    outer.addLayout(bulk)

    outer.addWidget(QLabel("<b>Log</b>"))
    self.log_pane = QPlainTextEdit()
    self.log_pane.setReadOnly(True)
    self.log_pane.setMaximumBlockCount(self.MAX_LOG_LINES)
    self.log_pane.setFont(QFont("Consolas", 9))
    outer.addWidget(self.log_pane, stretch=1)

    return w
```

- [ ] **Step 6: Replace `_wire_signals` to use QPushButton instead of QAction**

Replace the entire `_wire_signals` method with:

```python
def _wire_signals(self):
    self.bridge.log_sig.connect(self._log)
    self.bridge.status_sig.connect(self._on_status)
    self.bridge.progress_sig.connect(self._on_progress)

    self.btn_validate.clicked.connect(lambda: self._start("validate"))
    self.btn_discover.clicked.connect(lambda: self._start("discover_and_update_config"))
    self.btn_indexes.clicked.connect(lambda: self._start("rebuild_indexes"))
    self.btn_stop.clicked.connect(self._stop)
    self.btn_scrape_all.clicked.connect(lambda: self._start("scrape_all", {"force": False}))
    self.btn_force_all.clicked.connect(lambda: self._start("scrape_all", {"force": True}))
```

- [ ] **Step 7: Replace `_set_running` to use QPushButton instead of QAction**

Replace the entire `_set_running` method with:

```python
def _set_running(self, running: bool):
    for btn in (self.btn_validate, self.btn_discover, self.btn_indexes,
                self.btn_scrape_all, self.btn_force_all):
        btn.setEnabled(not running)
    for card in self.cards.values():
        card.set_enabled(not running)
    self.btn_stop.setEnabled(running)
```

- [ ] **Step 8: Remove the old QAction attributes from `_build_ui`**

Search `gui.py` for any remaining references to `self.act_validate`, `self.act_discover`, `self.act_indexes`, `self.act_stop` and delete them. These no longer exist.

- [ ] **Step 9: Launch the app and visually verify both tabs work**

```powershell
scraper\venv\Scripts\python.exe scraper\gui.py
```

Expected:
- App opens with two tabs: "v1 — Release Notes" and "v2 — Knowledge Base"
- v1 tab shows the 3 product cards (TradeDesk, Web4, SalesHub) with Validate / Discover / Rebuild Indexes / STOP buttons at top
- v2 tab shows grouped space cards (TradeDesk KB, Web 2.0 KB, Web 4.0 KB, API KB, SalesHub KB, Other) with Validate / Rebuild Indexes / STOP buttons at top
- Switching tabs does not affect the other tab's state
- v1 "Validate" button triggers discovery and logs results in the v1 log pane only
- v2 "Validate" button triggers KB space validation and logs in the v2 log pane only

- [ ] **Step 10: Run all tests one final time**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 11: Commit**

```powershell
git add scraper/gui.py
git commit -m "feat: add QTabWidget — v1 Release Notes and v2 Knowledge Base tabs"
```

---

## Final Smoke Test

After all tasks are committed, run a single-space scrape to verify the full pipeline end-to-end:

- [ ] Launch the app: `scraper\venv\Scripts\python.exe scraper\gui.py`
- [ ] Switch to "v2 — Knowledge Base" tab
- [ ] On the **System Administration** card, click **Scrape**
- [ ] Watch the log — expect `[OK] How to Configure and Test Email` etc.
- [ ] After completion, confirm files exist:

```powershell
Get-ChildItem "library\kb\tradedesk\system_administration" | Select-Object -First 10
```

Expected: `.json` and `.md` files per article, plus `screenshots/` folder.

- [ ] Check one Markdown file looks correct:

```powershell
Get-Content "library\kb\tradedesk\system_administration\how_to_configure_and_test_email.md" -TotalCount 20
```

Expected: YAML frontmatter followed by Markdown body with headings and numbered steps.
