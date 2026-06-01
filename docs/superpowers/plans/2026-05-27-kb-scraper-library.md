# Contoso KB Scraper & Release Notes Library — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python + Playwright scraper that extracts Release Notes for TradeDesk, Web4, and SalesHub from help.contoso.example and saves them as a local JSON + Markdown library with per-page screenshots.

**Architecture:** Modular scraper with a universal parser that adapts to whatever sections/tables are present on each page. A `Browser` class wraps Playwright headed-Chrome, a `StateTracker` handles incremental runs, and separate writer modules produce JSON + Markdown output. A `Launch.bat` interactive menu is the user-facing entry point.

**Tech Stack:** Python 3.10+, Playwright (chromium/Chrome headed), BeautifulSoup4, lxml, pytest

---

## File Map

```
Knowledge Base/
├── scraper/
│   ├── __init__.py
│   ├── Launch.bat          ← interactive menu entry point
│   ├── run.py              ← CLI orchestrator
│   ├── traverse.py         ← Phase 1: URL discovery script
│   ├── core.py             ← Browser + StateTracker
│   ├── config.py           ← product configs, paths
│   ├── requirements.txt
│   ├── state/
│   │   └── scraped_versions.json
│   ├── parsers/
│   │   ├── __init__.py
│   │   └── universal.py
│   └── writers/
│       ├── __init__.py
│       ├── json_writer.py
│       ├── md_writer.py
│       └── index_generator.py
├── library/                ← created during scrape run
│   ├── tradedesk/
│   │   ├── versions/  (3.0.19.json, 3.0.19.md, screenshots/3.0.19.png)
│   │   ├── CHANGELOG.md
│   │   ├── features-list.md
│   │   └── bugs-list.md
│   ├── web4/  (same structure)
│   ├── saleshub/  (same structure)
│   └── INDEX.md
└── tests/
    ├── fixtures/
    │   ├── tradedesk_sample.html
    │   ├── web4_sample.html
    │   └── saleshub_sample.html
    ├── test_universal_parser.py
    ├── test_json_writer.py
    ├── test_md_writer.py
    └── test_index_generator.py
```

---

## Task 1: Project Setup

**Files:**
- Create: `scraper/requirements.txt`
- Create: `scraper/__init__.py`
- Create: `scraper/parsers/__init__.py`
- Create: `scraper/writers/__init__.py`
- Create: `scraper/state/scraped_versions.json`

- [ ] **Step 1: Create folder structure**

Run from `Knowledge Base/` directory:
```powershell
New-Item -ItemType Directory -Force scraper\parsers
New-Item -ItemType Directory -Force scraper\writers
New-Item -ItemType Directory -Force scraper\state
New-Item -ItemType Directory -Force tests\fixtures
```

- [ ] **Step 2: Create requirements.txt**

`scraper/requirements.txt`:
```
playwright>=1.40.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
pytest>=7.4.0
```

- [ ] **Step 3: Create empty __init__.py files**

```powershell
"" | Out-File -FilePath scraper\__init__.py -Encoding utf8
"" | Out-File -FilePath scraper\parsers\__init__.py -Encoding utf8
"" | Out-File -FilePath scraper\writers\__init__.py -Encoding utf8
```

- [ ] **Step 4: Create initial empty state file**

`scraper/state/scraped_versions.json`:
```json
{}
```

- [ ] **Step 5: Create virtual environment and install dependencies**

```powershell
cd scraper
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cd ..
```

Expected output: `Playwright chromium installed` (or similar)

- [ ] **Step 6: Verify install**

```powershell
scraper\venv\Scripts\python.exe -c "from playwright.sync_api import sync_playwright; print('playwright OK')"
scraper\venv\Scripts\python.exe -c "from bs4 import BeautifulSoup; print('bs4 OK')"
```

Expected: `playwright OK` then `bs4 OK`

---

## Task 2: Site Traversal Script

**Files:**
- Modify: `scraper/traverse.py`
- Output: `scraper/state/url_map.json` (reference copy of discovered URLs)
- Side-effect: **auto-updates `scraper/config.py`** with the discovered `release_notes_url` values

`traverse.py` navigates headed Chrome to each product's release notes index, collects ALL version links via three strategies, then patches `config.py` in-place. No manual URL copy-paste step needed.

**Key structures in traverse.py:**

```python
# Known candidate URLs tried in priority order — first one with version links wins
PRODUCT_CANDIDATES = {
    "tradedesk": [
        "https://help.contoso.example/category/td",
        "https://help.contoso.example/display/TD",
        "https://help.contoso.example/display/TradeDesk",
    ],
    "web4": [
        "https://help.contoso.example/display/ReleaseNotesWeb4",   # confirmed working
        "https://help.contoso.example/category/web40",
        "https://help.contoso.example/category/web",
    ],
    "saleshub": [
        "https://help.contoso.example/category/sh",
        "https://help.contoso.example/display/SH",
        "https://help.contoso.example/display/SalesHub",
    ],
}

# Confluence sidebar selectors (AJAX-loaded page tree)
SIDEBAR_SELECTORS = [
    ".plugin_pagetree_children_list a",
    "#splitter-sidebar .pagetree-children a",
    ".ia-splitter-left a",
    ".aui-nav-tree a",
    "#content-tree a",
    "[data-testid='navigation-tree'] a",
    ".child-pages-container a",
]
```

**Three discovery strategies (applied in order, deduplicated):**
1. `collect_from_rest_api()` — Confluence REST API (`/rest/api/content?spaceKey=X`) with pagination
2. `collect_from_sidebar()` — tries all 7 sidebar CSS selectors
3. `collect_from_content()` — scans all `<a>` tags in page HTML

`scroll_and_expand()` scrolls the page and clicks Confluence expand buttons before collection to trigger AJAX loading.

`update_config_py()` string-patches `config.py` in-place, replacing each empty `"release_notes_url": ""` with the discovered URL.

- [x] **Step 1: traverse.py is already implemented** — see `scraper/traverse.py`

- [ ] **Step 2: Run the traversal script**

```powershell
cd "C:\Users\AbdulRaqeebKhatri\OneDrive\Documents\Knowledge Base"
scraper\venv\Scripts\python.exe scraper\traverse.py
```

A Chrome window opens. Watch it navigate to each product's release notes index and collect version links.

Expected output ends with:
```
config.py has been updated. You can now run Launch.bat directly.
```

- [ ] **Step 3: Verify config.py was auto-updated**

```powershell
scraper\venv\Scripts\python.exe -c "
import sys; sys.path.insert(0, '.')
from scraper.config import PRODUCTS
for k, v in PRODUCTS.items():
    ok = bool(v['release_notes_url'])
    print(f'{k}: {\"OK\" if ok else \"MISSING\"} ({v[\"release_notes_url\"]})')
"
```

Expected: all three products show `OK` with their URLs. Also check `scraper/state/url_map.json` for the full list of discovered version links per product.

---

## Task 3: config.py

**Files:**
- Create: `scraper/config.py`

- [ ] **Step 1: Create config.py**

`scraper/config.py`:
```python
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent.parent   # Knowledge Base/
LIBRARY_BASE = BASE_DIR / "library"
STATE_FILE   = Path(__file__).parent / "state" / "scraped_versions.json"

# ── Products ──────────────────────────────────────────────────────────────────
# These URLs are auto-populated by running: python scraper/traverse.py
# Do not edit manually — run traverse.py to update them.

PRODUCTS: dict[str, dict] = {
    "tradedesk": {
        "display_name": "TradeDesk",
        "release_notes_url": "",   # set by traverse.py
        "section_aliases": {
            "enhancements": [
                "enhancements and new features",
                "enhancements",
                "new features",
                "enhancement",
            ],
            "bugs": ["bugs", "bug fixes", "bug"],
            "schema_changes": ["schema changes", "database changes", "schema"],
        },
    },
    "web4": {
        "display_name": "Web4",
        "release_notes_url": "",   # set by traverse.py
        "section_aliases": {
            "enhancements": [
                "enhancements and new features",
                "enhancements",
                "new features",
            ],
            "bugs": ["bugs", "bug fixes"],
            "schema_changes": ["schema changes", "database changes"],
        },
    },
    "saleshub": {
        "display_name": "SalesHub",
        "release_notes_url": "",   # set by traverse.py
        "section_aliases": {
            "enhancements": [
                "enhancements and new features",
                "enhancements",
                "new features",
            ],
            "bugs": ["bugs", "bug fixes"],
            "schema_changes": ["schema changes", "database changes"],
        },
    },
}
```

- [ ] **Step 2: Verify config imports correctly** (URLs are auto-populated by traverse.py)

```powershell
scraper\venv\Scripts\python.exe -c "
import sys
sys.path.insert(0, '.')
from scraper.config import PRODUCTS, LIBRARY_BASE
print('LIBRARY_BASE:', LIBRARY_BASE)
for k, v in PRODUCTS.items():
    status = 'OK' if v['release_notes_url'] else 'MISSING'
    print(f'{k}: {status} ({v[\"release_notes_url\"]})')
"
```

Expected: all three products show `OK` with their URLs.

---

## Task 4: core.py — Browser & StateTracker

**Files:**
- Create: `scraper/core.py`

- [ ] **Step 1: Create core.py**

`scraper/core.py`:
```python
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from typing import Optional
import json

from playwright.sync_api import sync_playwright, Page, Browser as PWBrowser


class Browser:
    """Headed Chrome browser wrapper using Playwright."""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self._playwright = None
        self._browser: Optional[PWBrowser] = None
        self._page: Optional[Page] = None

    def open(self) -> "Browser":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            channel="chrome",
        )
        self._page = self._browser.new_page()
        return self

    def close(self):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def __enter__(self) -> "Browser":
        return self.open()

    def __exit__(self, *_):
        self.close()

    def navigate(self, url: str, wait_until: str = "networkidle"):
        self._page.goto(url, wait_until=wait_until, timeout=30_000)

    def expand_confluence_macros(self):
        """Click all Confluence expand macros to reveal hidden content before scraping."""
        selectors = [
            ".expand-control",
            "[data-macro-name='expand'] .expand-control-text",
            ".aui-expander-trigger",
            "a.expand-control",
        ]
        for selector in selectors:
            try:
                buttons = self._page.locator(selector).all()
                for btn in buttons:
                    try:
                        btn.click(timeout=1_000)
                        self._page.wait_for_timeout(200)
                    except Exception:
                        pass
            except Exception:
                pass

    def screenshot(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=path, full_page=True)

    def get_content(self) -> str:
        return self._page.content()

    def current_url(self) -> str:
        return self._page.url


class StateTracker:
    """Tracks which versions have been scraped to support incremental runs."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._state: dict = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)

    def is_scraped(self, product: str, version: str) -> bool:
        return version in self._state.get(product, {})

    def mark_scraped(self, product: str, version: str, url: str):
        if product not in self._state:
            self._state[product] = {}
        self._state[product][version] = {
            "url": url,
            "scraped_at": datetime.now().isoformat(),
        }
        self._save()

    def get_scraped_versions(self, product: str) -> dict:
        return self._state.get(product, {})
```

- [ ] **Step 2: Verify import**

```powershell
scraper\venv\Scripts\python.exe -c "
import sys; sys.path.insert(0, '.')
from scraper.core import Browser, StateTracker
print('core.py OK')
"
```

Expected: `core.py OK`

---

## Task 5: parsers/universal.py (TDD)

**Files:**
- Create: `tests/fixtures/tradedesk_sample.html`
- Create: `tests/fixtures/web4_sample.html`
- Create: `tests/fixtures/saleshub_sample.html`
- Create: `tests/test_universal_parser.py`
- Create: `scraper/parsers/universal.py`

- [ ] **Step 1: Create HTML fixtures**

`tests/fixtures/tradedesk_sample.html`:
```html
<!DOCTYPE html>
<html><body>
  <div id="main-content"><div class="wiki-content">
    <h1>Version 3.0.19</h1>
    <h2>Enhancements and New Features</h2>
    <ul>
      <li>12345 - Added real-time FX rate dashboard widget</li>
      <li>67890 - Improved deal booking workflow performance</li>
    </ul>
    <h2>Bugs</h2>
    <ul>
      <li>11111 - Fixed null pointer in trade confirmation module</li>
    </ul>
    <h2>Schema Changes</h2>
    <ul>
      <li>Added column last_modified_by to the deals table</li>
    </ul>
  </div></div>
</body></html>
```

`tests/fixtures/web4_sample.html`:
```html
<!DOCTYPE html>
<html><body>
  <div id="main-content"><div class="wiki-content">
    <h1>Version 4.0.2.2</h1>
    <table>
      <tr>
        <th>S.No</th><th>TFS/Portal ID</th><th>Details</th>
        <th>Configuration Changes</th><th>Key Feature</th>
        <th>Is there a change to previous behavior?</th><th>Risk Assessment</th>
      </tr>
      <tr>
        <td>1</td><td>55103</td><td>Enhanced Post-Deal Navigation in Web 4.0</td>
        <td>NO</td><td>NO</td><td>NO</td><td>LOW</td>
      </tr>
      <tr>
        <td>2</td><td>55104</td><td>Updated payment confirmation flow</td>
        <td>YES</td><td>YES</td><td>YES</td><td>MEDIUM</td>
      </tr>
    </table>
  </div></div>
</body></html>
```

`tests/fixtures/saleshub_sample.html`:
```html
<!DOCTYPE html>
<html><body>
  <div id="main-content"><div class="wiki-content">
    <h1>SalesHub WEB Version 2.0.2.1</h1>
    <h2>Enhancements and New Features</h2>
    <ul>
      <li>TFS-22222 - New lead scoring algorithm implemented</li>
    </ul>
    <h2>Bugs</h2>
    <ul>
      <li>TFS-33333 - Fixed dashboard loading issue on slow connections</li>
      <li>TFS-44444 - Resolved date formatting bug in reports</li>
    </ul>
  </div></div>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

`tests/test_universal_parser.py`:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.parsers.universal import parse_page, _extract_tfs_id

FIXTURES = Path(__file__).parent / "fixtures"

ALIASES = {
    "enhancements": ["enhancements and new features", "enhancements", "new features"],
    "bugs": ["bugs", "bug fixes", "bug"],
    "schema_changes": ["schema changes", "database changes"],
}


def html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# TradeDesk tests
def test_tradedesk_extracts_enhancements():
    r = parse_page(html("tradedesk_sample.html"), "tradedesk", "3.0.19", "http://x", "s.png", ALIASES)
    assert "enhancements" in r
    assert len(r["enhancements"]) == 2


def test_tradedesk_extracts_bugs():
    r = parse_page(html("tradedesk_sample.html"), "tradedesk", "3.0.19", "http://x", "s.png", ALIASES)
    assert "bugs" in r
    assert len(r["bugs"]) == 1


def test_tradedesk_extracts_schema_changes():
    r = parse_page(html("tradedesk_sample.html"), "tradedesk", "3.0.19", "http://x", "s.png", ALIASES)
    assert "schema_changes" in r
    assert len(r["schema_changes"]) == 1


def test_tradedesk_enhancement_has_tfs_id():
    r = parse_page(html("tradedesk_sample.html"), "tradedesk", "3.0.19", "http://x", "s.png", ALIASES)
    assert r["enhancements"][0]["id"] == "12345"


def test_tradedesk_description_strips_id_prefix():
    r = parse_page(html("tradedesk_sample.html"), "tradedesk", "3.0.19", "http://x", "s.png", ALIASES)
    assert not r["enhancements"][0]["description"].startswith("12345")


# Web4 tests
def test_web4_extracts_tasks_table():
    r = parse_page(html("web4_sample.html"), "web4", "4.0.2.2", "http://x", "s.png", ALIASES)
    assert "tasks" in r
    assert len(r["tasks"]) == 2


def test_web4_task_columns_mapped():
    r = parse_page(html("web4_sample.html"), "web4", "4.0.2.2", "http://x", "s.png", ALIASES)
    t = r["tasks"][0]
    assert t["tfs_id"] == "55103"
    assert "Enhanced Post-Deal" in t["details"]
    assert t["risk"] == "LOW"


def test_web4_no_enhancements_section_when_absent():
    r = parse_page(html("web4_sample.html"), "web4", "4.0.2.2", "http://x", "s.png", ALIASES)
    assert "enhancements" not in r


# SalesHub tests
def test_saleshub_extracts_enhancements_and_bugs():
    r = parse_page(html("saleshub_sample.html"), "saleshub", "2.0.2.1", "http://x", "s.png", ALIASES)
    assert "enhancements" in r and "bugs" in r
    assert len(r["bugs"]) == 2


def test_saleshub_no_schema_changes_when_absent():
    r = parse_page(html("saleshub_sample.html"), "saleshub", "2.0.2.1", "http://x", "s.png", ALIASES)
    assert "schema_changes" not in r


def test_saleshub_tfs_prefix_extracted():
    r = parse_page(html("saleshub_sample.html"), "saleshub", "2.0.2.1", "http://x", "s.png", ALIASES)
    assert r["bugs"][0]["id"] == "TFS-33333"


# Metadata tests
def test_result_contains_required_metadata():
    r = parse_page(html("tradedesk_sample.html"), "tradedesk", "3.0.19", "http://example.com", "shot.png", ALIASES)
    assert r["product"] == "tradedesk"
    assert r["version"] == "3.0.19"
    assert r["url"] == "http://example.com"
    assert r["screenshot"] == "shot.png"
    assert "scraped_at" in r


# _extract_tfs_id tests
def test_tfs_id_numeric():
    tfs_id, desc = _extract_tfs_id("12345 - Fixed something important")
    assert tfs_id == "12345"
    assert "Fixed something" in desc


def test_tfs_id_tfs_prefix():
    tfs_id, desc = _extract_tfs_id("TFS-67890 - New feature added")
    assert tfs_id == "TFS-67890"
    assert "New feature" in desc


def test_tfs_id_none_when_no_id():
    tfs_id, desc = _extract_tfs_id("Some change without an ID")
    assert tfs_id is None
    assert desc == "Some change without an ID"


def test_tfs_id_does_not_match_short_numbers():
    tfs_id, desc = _extract_tfs_id("Minor fix in 3.0.19 release")
    assert tfs_id is None
```

- [ ] **Step 3: Run tests — confirm FAIL (module not found)**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_universal_parser.py -v 2>&1 | Select-Object -First 20
```

Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 4: Create universal.py**

`scraper/parsers/universal.py`:
```python
from __future__ import annotations
from bs4 import BeautifulSoup, Tag
from datetime import datetime
from typing import Optional
import re


def parse_page(
    html: str,
    product: str,
    version: str,
    url: str,
    screenshot_path: str,
    section_aliases: dict[str, list[str]],
) -> dict:
    """
    Parse a Confluence release notes page.
    Returns a dict with only the fields actually present on the page.
    """
    soup = BeautifulSoup(html, "lxml")
    result: dict = {
        "product": product,
        "version": version,
        "url": url,
        "scraped_at": datetime.now().isoformat(),
        "screenshot": screenshot_path,
    }

    content = _find_content_area(soup)

    tasks = _extract_table(content)
    if tasks:
        result["tasks"] = tasks

    for field_name, aliases in section_aliases.items():
        items = _extract_section(content, aliases)
        if items:
            result[field_name] = items

    return result


def _find_content_area(soup: BeautifulSoup) -> Tag:
    for selector in [
        "#main-content", ".wiki-content", "#content",
        ".confluenceContent", "article", "main",
    ]:
        el = soup.select_one(selector)
        if el:
            return el
    return soup


_COLUMN_MAP: dict[str, str] = {
    "s.no": "sno", "sno": "sno", "#": "sno", "no": "sno",
    "tfs/portal id": "tfs_id", "tfs id": "tfs_id", "portal id": "tfs_id", "id": "tfs_id",
    "details": "details", "description": "details", "detail": "details",
    "configuration changes": "config_changes", "config changes": "config_changes",
    "key feature": "key_feature",
    "is there a change to previous behavior?": "behavior_change",
    "behavior change": "behavior_change",
    "change to previous behavior": "behavior_change",
    "risk assessment": "risk", "risk": "risk",
}


def _extract_table(content: Tag) -> list[dict]:
    table = content.find("table")
    if not table:
        return []
    rows = table.find_all("tr")
    if len(rows) < 2:
        return []
    raw_headers = [c.get_text(strip=True).lower() for c in rows[0].find_all(["th", "td"])]
    headers = [_COLUMN_MAP.get(h, h) for h in raw_headers]
    tasks = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        task: dict = {}
        for i, cell in enumerate(cells):
            if i < len(headers):
                task[headers[i]] = cell.get_text(separator=" ", strip=True)
        if any(v for v in task.values()):
            tasks.append(task)
    return tasks


def _extract_section(content: Tag, aliases: list[str]) -> list[dict]:
    for heading in content.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if any(alias in heading.get_text(strip=True).lower() for alias in aliases):
            return _extract_items_after_heading(heading)
    return []


def _extract_items_after_heading(heading: Tag) -> list[dict]:
    items: list[dict] = []
    node = heading.next_sibling
    while node is not None:
        if isinstance(node, Tag):
            if node.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                break
            if node.name in ("ul", "ol"):
                for li in node.find_all("li", recursive=False):
                    text = li.get_text(separator=" ", strip=True)
                    if text:
                        item = _make_item(text)
                        if item:
                            items.append(item)
            elif node.name == "p":
                text = node.get_text(separator=" ", strip=True)
                if text and "click here" not in text.lower():
                    item = _make_item(text)
                    if item:
                        items.append(item)
        node = node.next_sibling
    return items


def _make_item(text: str) -> Optional[dict]:
    text = text.strip()
    if not text:
        return None
    tfs_id, description = _extract_tfs_id(text)
    item: dict = {"description": description}
    if tfs_id:
        item["id"] = tfs_id
    return item


_TFS_PATTERN = re.compile(
    r"^(TFS-\d+|#?\d{4,6})\s*[-:]\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _extract_tfs_id(text: str) -> tuple[Optional[str], str]:
    m = _TFS_PATTERN.match(text.strip())
    if m:
        return m.group(1).lstrip("#"), m.group(2).strip()
    return None, text
```

- [ ] **Step 5: Run tests — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_universal_parser.py -v
```

Expected: all tests green.

---

## Task 6: writers/json_writer.py (TDD)

**Files:**
- Create: `tests/test_json_writer.py`
- Create: `scraper/writers/json_writer.py`

- [ ] **Step 1: Write failing tests**

`tests/test_json_writer.py`:
```python
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.writers.json_writer import save_version

SAMPLE = {
    "product": "tradedesk",
    "version": "3.0.19",
    "url": "http://example.com",
    "scraped_at": "2026-05-27T10:00:00",
    "enhancements": [{"id": "12345", "description": "New feature"}],
    "bugs": [{"description": "Bug fix"}],
    "screenshot": "library/tradedesk/versions/screenshots/3.0.19.png",
}


def test_creates_json_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(SAMPLE, Path(tmp))
        assert path.exists() and path.suffix == ".json"


def test_json_content_matches_input():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(SAMPLE, Path(tmp))
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["version"] == "3.0.19"
        assert loaded["product"] == "tradedesk"
        assert len(loaded["enhancements"]) == 1


def test_file_path_uses_product_and_version():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(SAMPLE, Path(tmp))
        assert "tradedesk" in str(path)
        assert "versions" in str(path)
        assert "3.0.19" in path.name


def test_version_spaces_become_underscores():
    data = {**SAMPLE, "version": "Version 3.0.19"}
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(data, Path(tmp))
        assert " " not in path.name
```

- [ ] **Step 2: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_json_writer.py -v 2>&1 | Select-Object -First 10
```

- [ ] **Step 3: Create json_writer.py**

`scraper/writers/json_writer.py`:
```python
from __future__ import annotations
import json
from pathlib import Path


def save_version(data: dict, library_base: Path) -> Path:
    """Save parsed version data as JSON. Returns the path written."""
    safe_version = _safe_name(data["version"])
    output_dir = library_base / data["product"] / "versions"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_version}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return output_path


def _safe_name(version: str) -> str:
    return version.replace(" ", "_").replace("/", "-").strip()
```

- [ ] **Step 4: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_json_writer.py -v
```

---

## Task 7: writers/md_writer.py (TDD)

**Files:**
- Create: `tests/test_md_writer.py`
- Create: `scraper/writers/md_writer.py`

- [ ] **Step 1: Write failing tests**

`tests/test_md_writer.py`:
```python
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.writers.md_writer import save_version, _render_md

SECTIONS = {
    "product": "tradedesk", "version": "3.0.19",
    "url": "http://example.com", "scraped_at": "2026-05-27T10:00:00",
    "enhancements": [{"id": "12345", "description": "New feature"}],
    "bugs": [{"description": "Bug fix"}],
    "schema_changes": [{"description": "Added column X"}],
    "screenshot": "library/tradedesk/versions/screenshots/3.0.19.png",
}

TABLE = {
    "product": "web4", "version": "4.0.2.2",
    "url": "http://example.com", "scraped_at": "2026-05-27T10:00:00",
    "tasks": [{"sno": "1", "tfs_id": "55103", "details": "Enhanced navigation",
               "config_changes": "NO", "key_feature": "NO",
               "behavior_change": "NO", "risk": "LOW"}],
    "screenshot": "library/web4/versions/screenshots/4.0.2.2.png",
}


def test_render_includes_version():
    assert "3.0.19" in _render_md(SECTIONS)


def test_render_includes_enhancements():
    md = _render_md(SECTIONS)
    assert "Enhancements" in md and "New feature" in md


def test_render_includes_tfs_id():
    assert "12345" in _render_md(SECTIONS)


def test_render_includes_bugs():
    md = _render_md(SECTIONS)
    assert "Bugs" in md and "Bug fix" in md


def test_render_omits_absent_sections():
    data = {k: v for k, v in SECTIONS.items() if k != "schema_changes"}
    assert "Schema" not in _render_md(data)


def test_render_table_for_tasks():
    md = _render_md(TABLE)
    assert "55103" in md and "Enhanced navigation" in md


def test_save_creates_md_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(SECTIONS, Path(tmp))
        assert path.exists() and path.suffix == ".md"


def test_save_path_uses_product_and_version():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(SECTIONS, Path(tmp))
        assert "tradedesk" in str(path) and "3.0.19" in path.name
```

- [ ] **Step 2: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_md_writer.py -v 2>&1 | Select-Object -First 10
```

- [ ] **Step 3: Create md_writer.py**

`scraper/writers/md_writer.py`:
```python
from __future__ import annotations
from pathlib import Path


def save_version(data: dict, library_base: Path) -> Path:
    """Save parsed version data as Markdown. Returns the path written."""
    safe_ver = data["version"].replace(" ", "_").replace("/", "-").strip()
    output_dir = library_base / data["product"] / "versions"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_ver}.md"
    output_path.write_text(_render_md(data), encoding="utf-8")
    return output_path


def _render_md(data: dict) -> str:
    lines: list[str] = []
    display = data["product"].replace("_", " ").title()
    lines += [
        f"# {display} — Version {data['version']}",
        "",
        f"**URL:** {data['url']}  ",
        f"**Scraped:** {data['scraped_at']}",
        "",
    ]
    if data.get("screenshot"):
        lines += [f"**Screenshot:** `{data['screenshot']}`", ""]

    if data.get("enhancements"):
        lines += ["## Enhancements and New Features", ""]
        for item in data["enhancements"]:
            prefix = f"**{item['id']}** — " if item.get("id") else ""
            lines.append(f"- {prefix}{item['description']}")
        lines.append("")

    if data.get("bugs"):
        lines += ["## Bugs", ""]
        for item in data["bugs"]:
            prefix = f"**{item['id']}** — " if item.get("id") else ""
            lines.append(f"- {prefix}{item['description']}")
        lines.append("")

    if data.get("schema_changes"):
        lines += ["## Schema Changes", ""]
        for item in data["schema_changes"]:
            lines.append(f"- {item['description']}")
        lines.append("")

    if data.get("tasks"):
        cols = ["#", "TFS ID", "Details", "Config Changes", "Key Feature", "Behavior Change", "Risk"]
        keys = ["sno", "tfs_id", "details", "config_changes", "key_feature", "behavior_change", "risk"]
        lines += ["## Tasks", ""]
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("|" + "|".join(["---"] * len(cols)) + "|")
        for task in data["tasks"]:
            row = [str(task.get(k, "")) for k in keys]
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_md_writer.py -v
```

---

## Task 8: writers/index_generator.py (TDD)

**Files:**
- Create: `tests/test_index_generator.py`
- Create: `scraper/writers/index_generator.py`

- [ ] **Step 1: Write failing tests**

`tests/test_index_generator.py`:
```python
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.writers.index_generator import generate_all

PRODUCTS = {
    "tradedesk": {"display_name": "TradeDesk"},
    "web4":     {"display_name": "Web4"},
    "saleshub":  {"display_name": "SalesHub"},
}

V1 = {
    "product": "tradedesk", "version": "3.0.19",
    "url": "http://x/3.0.19", "scraped_at": "2026-05-27T10:00:00",
    "enhancements": [{"id": "1", "description": "Feature A"}],
    "bugs": [{"description": "Bug A"}],
    "screenshot": "",
}
V2 = {
    "product": "tradedesk", "version": "3.0.18",
    "url": "http://x/3.0.18", "scraped_at": "2026-05-27T09:00:00",
    "enhancements": [{"description": "Feature B"}],
    "screenshot": "",
}


def write_versions(library_base: Path, product: str, versions: list):
    d = library_base / product / "versions"
    d.mkdir(parents=True, exist_ok=True)
    for v in versions:
        (d / f"{v['version']}.json").write_text(json.dumps(v), encoding="utf-8")


def test_generates_changelog():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp)
        write_versions(lib, "tradedesk", [V1, V2])
        generate_all(lib, PRODUCTS)
        assert (lib / "tradedesk" / "CHANGELOG.md").exists()


def test_changelog_contains_both_versions():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp)
        write_versions(lib, "tradedesk", [V1, V2])
        generate_all(lib, PRODUCTS)
        text = (lib / "tradedesk" / "CHANGELOG.md").read_text()
        assert "3.0.19" in text and "3.0.18" in text


def test_features_list_contains_all_enhancements():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp)
        write_versions(lib, "tradedesk", [V1, V2])
        generate_all(lib, PRODUCTS)
        text = (lib / "tradedesk" / "features-list.md").read_text()
        assert "Feature A" in text and "Feature B" in text


def test_bugs_list_contains_bugs():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp)
        write_versions(lib, "tradedesk", [V1, V2])
        generate_all(lib, PRODUCTS)
        text = (lib / "tradedesk" / "bugs-list.md").read_text()
        assert "Bug A" in text


def test_master_index_contains_all_products():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp)
        write_versions(lib, "tradedesk", [V1, V2])
        generate_all(lib, PRODUCTS)
        index = (lib / "INDEX.md").read_text()
        assert "TradeDesk" in index and "Web4" in index and "SalesHub" in index


def test_empty_products_handled_gracefully():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp)
        generate_all(lib, PRODUCTS)   # no versions written — must not raise
        assert (lib / "INDEX.md").exists()
```

- [ ] **Step 2: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_index_generator.py -v 2>&1 | Select-Object -First 10
```

- [ ] **Step 3: Create index_generator.py**

`scraper/writers/index_generator.py`:
```python
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime


def generate_all(library_base: Path, products: dict):
    """Rebuild all per-product indexes and the master INDEX.md."""
    for key, cfg in products.items():
        _generate_product_indexes(library_base, key, cfg["display_name"])
    _generate_master_index(library_base, products)


def _load_versions(library_base: Path, product: str) -> list[dict]:
    versions_dir = library_base / product / "versions"
    if not versions_dir.exists():
        return []
    result = []
    for f in sorted(versions_dir.glob("*.json"), reverse=True):
        try:
            result.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return result


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _safe(version: str) -> str:
    return version.replace(" ", "_")


def _generate_product_indexes(library_base: Path, product: str, display_name: str):
    versions = _load_versions(library_base, product)
    product_dir = library_base / product
    product_dir.mkdir(parents=True, exist_ok=True)

    # CHANGELOG
    lines = [f"# {display_name} — Changelog", "", f"*Generated: {_now()}*", "", "---", ""]
    for v in versions:
        parts = []
        if v.get("enhancements"):
            parts.append(f"{len(v['enhancements'])} enhancement(s)")
        if v.get("bugs"):
            parts.append(f"{len(v['bugs'])} bug fix(es)")
        if v.get("tasks"):
            parts.append(f"{len(v['tasks'])} task(s)")
        if v.get("schema_changes"):
            parts.append(f"{len(v['schema_changes'])} schema change(s)")
        summary = ", ".join(parts) if parts else "no items extracted"
        lines += [
            f"## Version {v['version']}", "",
            f"*{v['url']}*", "",
            f"**Summary:** {summary}", "",
            f"[View details](versions/{_safe(v['version'])}.md)", "",
            "---", "",
        ]
    (product_dir / "CHANGELOG.md").write_text("\n".join(lines), encoding="utf-8")

    # features-list
    lines = [f"# {display_name} — All Features & Enhancements", "", f"*Generated: {_now()}*", "", "---", ""]
    for v in versions:
        if v.get("enhancements"):
            lines += [f"## Version {v['version']}", ""]
            for item in v["enhancements"]:
                prefix = f"**{item['id']}** — " if item.get("id") else ""
                lines.append(f"- {prefix}{item['description']}")
            lines.append("")
    (product_dir / "features-list.md").write_text("\n".join(lines), encoding="utf-8")

    # bugs-list
    lines = [f"# {display_name} — All Bug Fixes", "", f"*Generated: {_now()}*", "", "---", ""]
    for v in versions:
        if v.get("bugs"):
            lines += [f"## Version {v['version']}", ""]
            for item in v["bugs"]:
                prefix = f"**{item['id']}** — " if item.get("id") else ""
                lines.append(f"- {prefix}{item['description']}")
            lines.append("")
    (product_dir / "bugs-list.md").write_text("\n".join(lines), encoding="utf-8")


def _generate_master_index(library_base: Path, products: dict):
    lines = [
        "# Contoso Knowledge Base — Release Notes Library", "",
        f"*Generated: {_now()}*", "", "---", "",
    ]
    for key, cfg in products.items():
        versions = _load_versions(library_base, key)
        display = cfg["display_name"]
        lines += [
            f"## {display}", "",
            f"**{len(versions)} version(s) scraped**", "",
            f"- [Changelog]({key}/CHANGELOG.md)",
            f"- [All Features]({key}/features-list.md)",
            f"- [All Bugs]({key}/bugs-list.md)", "",
        ]
        if versions:
            lines.append("**Versions:**")
            lines.append("")
            for v in versions[:10]:
                lines.append(f"- [{v['version']}]({key}/versions/{_safe(v['version'])}.md)")
            if len(versions) > 10:
                lines.append(f"- *... and {len(versions) - 10} more — see [Changelog]({key}/CHANGELOG.md)*")
            lines.append("")
        lines += ["---", ""]
    library_base.mkdir(parents=True, exist_ok=True)
    (library_base / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
```

- [ ] **Step 4: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_index_generator.py -v
```

- [ ] **Step 5: Run full test suite — all green**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: all tests across all four test files pass.

---

## Task 9: run.py — CLI Orchestrator

**Files:**
- Create: `scraper/run.py`

- [ ] **Step 1: Create run.py**

`scraper/run.py`:
```python
"""
Contoso KB Scraper — CLI orchestrator.
Typically invoked via Launch.bat. Can also be run directly:
  python scraper/run.py --all
  python scraper/run.py --product tradedesk
  python scraper/run.py --product web4 --force
  python scraper/run.py --index-only
"""
from __future__ import annotations
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.config import PRODUCTS, LIBRARY_BASE, STATE_FILE
from scraper.core import Browser, StateTracker
from scraper.parsers.universal import parse_page
from scraper.writers import json_writer, md_writer, index_generator
from bs4 import BeautifulSoup


def discover_versions(browser: Browser, product_key: str) -> list[dict]:
    """Navigate to the release notes index and collect all version links."""
    release_notes_url = PRODUCTS[product_key]["release_notes_url"]
    if not release_notes_url:
        print(f"  ERROR: No release_notes_url set for '{product_key}'. "
              "Run traverse.py and update config.py.")
        return []

    print(f"  Discovering: {release_notes_url}")
    browser.navigate(release_notes_url)

    soup = BeautifulSoup(browser.get_content(), "lxml")
    base = "https://help.contoso.example"
    seen: set[str] = set()
    versions: list[dict] = []

    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]
        if not text or not any(ch.isdigit() for ch in text):
            continue
        full_url = href if href.startswith("http") else f"{base}{href}"
        if base not in full_url or full_url == release_notes_url or full_url in seen:
            continue
        seen.add(full_url)
        versions.append({"version": text, "url": full_url})

    return versions


def scrape_product(product_key: str, force: bool = False):
    cfg = PRODUCTS[product_key]
    display_name = cfg["display_name"]
    tracker = StateTracker(STATE_FILE)

    print(f"\n{'='*55}")
    print(f"  {display_name}")
    print(f"{'='*55}")

    with Browser(headless=False) as browser:
        versions = discover_versions(browser, product_key)
        print(f"  Found {len(versions)} version link(s)")

        new_count = skipped_count = error_count = 0

        for v in versions:
            version_str = v["version"]
            version_url = v["url"]

            if not force and tracker.is_scraped(product_key, version_str):
                print(f"  [SKIP]   {version_str}")
                skipped_count += 1
                continue

            print(f"  [SCRAPE] {version_str}")
            try:
                browser.navigate(version_url)
                browser.expand_confluence_macros()

                safe_ver = version_str.replace(" ", "_").replace("/", "-")
                screenshot_path = str(
                    LIBRARY_BASE / product_key / "versions" / "screenshots" / f"{safe_ver}.png"
                )
                browser.screenshot(screenshot_path)

                data = parse_page(
                    html=browser.get_content(),
                    product=product_key,
                    version=version_str,
                    url=version_url,
                    screenshot_path=screenshot_path,
                    section_aliases=cfg["section_aliases"],
                )

                json_writer.save_version(data, LIBRARY_BASE)
                md_writer.save_version(data, LIBRARY_BASE)
                tracker.mark_scraped(product_key, version_str, version_url)

                enh = len(data.get("enhancements", []))
                bug = len(data.get("bugs", []))
                tsk = len(data.get("tasks", []))
                print(f"           enhancements={enh}  bugs={bug}  tasks={tsk}")
                new_count += 1

            except Exception as exc:
                print(f"  [ERROR]  {version_str}: {exc}")
                error_count += 1

        print(f"\n  {display_name}: {new_count} new, {skipped_count} skipped, {error_count} errors")


def rebuild_indexes():
    print("\nRebuilding indexes...")
    index_generator.generate_all(LIBRARY_BASE, PRODUCTS)
    print(f"  Done — written to {LIBRARY_BASE}")


def main():
    parser = argparse.ArgumentParser(description="Contoso KB Release Notes Scraper")
    parser.add_argument("--product", choices=list(PRODUCTS.keys()))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--index-only", action="store_true")
    args = parser.parse_args()

    if args.index_only:
        rebuild_indexes()
    elif args.all:
        for key in PRODUCTS:
            scrape_product(key, force=args.force)
        rebuild_indexes()
    elif args.product:
        scrape_product(args.product, force=args.force)
        rebuild_indexes()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify help text**

```powershell
scraper\venv\Scripts\python.exe scraper\run.py --help
```

Expected: usage/help text printed, no errors.

---

## Task 10: Launch.bat — Interactive Menu

**Files:**
- Create: `scraper/Launch.bat`

- [ ] **Step 1: Create Launch.bat**

`scraper/Launch.bat`:
```batch
@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM Change to Knowledge Base root (one level above this script)
cd /d "%~dp0.."

REM Activate venv if present
if exist "scraper\venv\Scripts\activate.bat" (
    call scraper\venv\Scripts\activate.bat
) else (
    echo [WARNING] Virtual environment not found. Using system Python.
    echo           Run Task 1 setup steps if this fails.
    echo.
)

:MENU
cls
echo.
echo  ============================================
echo    Contoso KB Scraper  -  Launch Menu
echo  ============================================
echo.
echo    1.  Scrape ALL products   (incremental)
echo    2.  Scrape TradeDesk only
echo    3.  Scrape Web4 only
echo    4.  Scrape SalesHub only
echo    5.  Force re-scrape ALL   (full refresh)
echo    6.  Force re-scrape TradeDesk
echo    7.  Force re-scrape Web4
echo    8.  Force re-scrape SalesHub
echo    9.  Rebuild index files only
echo    0.  Exit
echo.
set /p CHOICE="  Enter choice [0-9]: "

if "%CHOICE%"=="1" ( python scraper\run.py --all & goto DONE )
if "%CHOICE%"=="2" ( python scraper\run.py --product tradedesk & goto DONE )
if "%CHOICE%"=="3" ( python scraper\run.py --product web4 & goto DONE )
if "%CHOICE%"=="4" ( python scraper\run.py --product saleshub & goto DONE )
if "%CHOICE%"=="5" ( python scraper\run.py --all --force & goto DONE )
if "%CHOICE%"=="6" ( python scraper\run.py --product tradedesk --force & goto DONE )
if "%CHOICE%"=="7" ( python scraper\run.py --product web4 --force & goto DONE )
if "%CHOICE%"=="8" ( python scraper\run.py --product saleshub --force & goto DONE )
if "%CHOICE%"=="9" ( python scraper\run.py --index-only & goto DONE )
if "%CHOICE%"=="0" goto EXIT

echo  Invalid choice. Try again.
timeout /t 1 >nul
goto MENU

:DONE
echo.
echo  ─────────────────────────────────
echo   Done. Press any key for menu.
echo  ─────────────────────────────────
pause >nul
goto MENU

:EXIT
echo  Goodbye!
endlocal
```

- [ ] **Step 2: Test launcher opens with menu**

Double-click `scraper\Launch.bat` in Windows Explorer.

Expected: terminal opens showing the menu. Press `0` to exit cleanly.

---

## Task 11: Integration Run & Validation

- [ ] **Step 1: Run traverse.py to discover all URLs and auto-update config.py**

```powershell
cd "C:\Users\AbdulRaqeebKhatri\OneDrive\Documents\Knowledge Base"
scraper\venv\Scripts\python.exe scraper\traverse.py
```

Chrome opens and navigates to each product's release notes index. Expected final output:
```
config.py has been updated. You can now run Launch.bat directly.
```

Then verify:
```powershell
scraper\venv\Scripts\python.exe -c "
import sys; sys.path.insert(0, '.')
from scraper.config import PRODUCTS
for k, v in PRODUCTS.items():
    ok = bool(v['release_notes_url'])
    print(f'{k}: {\"OK\" if ok else \"MISSING\"} ({v[\"release_notes_url\"]})')
"
```

All three must show `OK` before proceeding.

- [ ] **Step 2: Smoke test — scrape TradeDesk only**

Launch.bat → option `2` (TradeDesk only).

Watch Chrome open. Expected console output:
```
=======================================================
  TradeDesk
=======================================================
  Discovering: https://help.contoso.example/...
  Found N version link(s)
  [SCRAPE] 3.x.x.x
           enhancements=N  bugs=N  tasks=N
  ...
```

- [ ] **Step 3: Check output files exist**

```powershell
Get-ChildItem "library\tradedesk\versions" -Recurse | Select-Object Name
```

Expected: `.json` files, `.md` files, `screenshots\` subfolder with `.png` files.

- [ ] **Step 4: Spot-check a JSON file**

```powershell
scraper\venv\Scripts\python.exe -c "
import json, sys
from pathlib import Path
files = sorted(Path('library/tradedesk/versions').glob('*.json'))
if not files:
    print('No JSON files found!')
    sys.exit(1)
data = json.loads(files[0].read_text())
print('version:', data.get('version'))
print('fields:', [k for k in data if k not in ('product','url','scraped_at','screenshot','version')])
"
```

Expected: version printed, at least one data field listed (enhancements, bugs, tasks, or schema_changes).

- [ ] **Step 5: Run all three products**

Launch.bat → option `1` (Scrape ALL incremental).

- [ ] **Step 6: Rebuild indexes**

Launch.bat → option `9` (Rebuild index files only).

```powershell
Get-ChildItem library -Recurse -Filter "*.md" | Select-Object Name
```

Expected: `INDEX.md`, `CHANGELOG.md`, `features-list.md`, `bugs-list.md` for each product.

- [ ] **Step 7: Final test suite run**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/ -v
```

Expected: all tests green.

---

## Quick Reference

| Goal | Action |
|------|--------|
| First-time setup | Task 1 steps 1–6 |
| Discover site URLs | `python scraper\traverse.py` |
| Normal scrape (all) | Launch.bat → `1` |
| Scrape one product | Launch.bat → `2` / `3` / `4` |
| Force full re-scrape | Launch.bat → `5` |
| Rebuild indexes only | Launch.bat → `9` |
| Run tests | `scraper\venv\Scripts\python.exe -m pytest tests/ -v` |
