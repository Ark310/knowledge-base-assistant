# Contoso KB Scraper V2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the Contoso KB scraper so discovery is deterministic (Confluence REST API keyed by known space keys), parsing is full-fidelity (each section heading's table captured with every column), and the runtime is production-grade (retries, logging, run reports, dry-run validation, a robust launcher).

**Architecture:** `discovery.py` lists version pages via the REST API (stdlib HTTP, no browser). `core.py` wraps headed Chrome (used only to render pages + screenshot) and tracks state. `parsers/universal.py` walks section headings and extracts the table that follows each, normalizing columns. `writers/` emit JSON/Markdown/indexes. `run.py` orchestrates with logging + a run report. `Launch.bat` is a self-diagnosing menu.

**Tech Stack:** Python 3.10+, Playwright (Chrome via `channel="chrome"`), BeautifulSoup4, lxml, pytest. Discovery uses stdlib `urllib`.

**Spec:** `docs/superpowers/specs/2026-05-27-kb-scraper-v2-design.md`

**This is a no-git environment** — there are no `git commit` steps. After each task, verification is the passing test run. The implementer must NOT run git commands.

---

## Ground-Truth Reference (verified live 2026-05-27)

Space keys and version counts (used as known-good defaults and test assertions):

| Product | `space_key` | `release_notes_url` | Version pages |
|---|---|---|---|
| tradedesk | `releasenotes` | `https://help.contoso.example/display/releasenotes` | 117 |
| web4 | `ReleaseNotesWeb4` | `https://help.contoso.example/display/ReleaseNotesWeb4` | 18 |
| saleshub | `SHReleaseNotes` | `https://help.contoso.example/display/SHReleaseNotes` | 21 |

Real sample pages used for fixtures and assertions:

- **SalesHub `SalesHub WEB Version 2.0.2.1`** — sections: Enhancements and New Features (8 rows, first `Portal/TFS ID`=`57196`), Bugs (3 rows, first=`57215`), Schema Changes (1 row: `Object Type`=Table, `Object Name`=WEB_FTF_DETAIL, `Action Type`=Altered). Has a "Table of Contents" heading (no table → ignored).
- **Web4 `Version 4.0.3.0`** — sections: Tasks (4 rows, first `TFS/Portal ID`=`71669`), Schema Changes (29 rows). No Enhancements/Bugs.
- **TradeDesk `Version 3.0.1.9`** — sections: Enhancements and New Features (9 rows, first `Task ID`=`14093`, `Module`=Dashboard Activity), Bugs (3 rows, first=`14081`), Schema Changes (9 rows, first `Type`=View).

DOM facts:
- Content root is `#main-content` (fallback `.wiki-content`, then `body`).
- A section's table is **not** a direct sibling of the heading — it sits in a following sibling (Confluence wraps tables in `div.table-wrap`). Parser must walk forward from the heading until the next heading, taking the first `<table>` that is either a sibling or nested inside a sibling.
- Header row = first `<tr>`; cells are `<th>` or `<td>`.
- The Risk column header is a long blob beginning `Risk assessment:` (SalesHub uses the short `Risk assessment`). Both normalize to `risk`.
- REST pagination: response has `start`, `limit`, `size`, `_links.next` (a relative path present only when more pages exist). Loop following `next` until absent. There is no `totalSize`.

---

## File Map

```
Knowledge Base/
├── scraper/
│   ├── __init__.py
│   ├── Launch.bat          ← robust menu (rewritten)
│   ├── run.py              ← orchestrator (rewritten)
│   ├── discovery.py        ← NEW
│   ├── core.py             ← Browser (retries) + StateTracker (rewritten)
│   ├── config.py           ← space keys, aliases, COLUMN_SYNONYMS, paths (rewritten)
│   ├── requirements.txt
│   ├── state/
│   │   ├── scraped_versions.json
│   │   ├── run.log              (created at runtime)
│   │   └── last_run_report.json (created at runtime)
│   ├── parsers/
│   │   ├── __init__.py
│   │   └── universal.py    ← rewritten
│   └── writers/
│       ├── __init__.py
│       ├── json_writer.py
│       ├── md_writer.py    ← rewritten (section tables)
│       └── index_generator.py ← rewritten (row dicts)
├── tests/
│   ├── fixtures/
│   │   ├── tradedesk_real.html   ← captured (Task 2)
│   │   ├── web4_real.html
│   │   ├── saleshub_real.html
│   │   ├── tradedesk_rest.json
│   │   ├── web4_rest.json
│   │   └── saleshub_rest.json
│   ├── capture_fixtures.py      ← NEW (Task 2)
│   ├── test_discovery.py
│   ├── test_universal_parser.py
│   ├── test_json_writer.py
│   ├── test_md_writer.py
│   ├── test_index_generator.py
│   └── test_config_roundtrip.py
└── library/   (created during scrape)
```

All commands assume the working directory is the Knowledge Base root:
`C:\Users\AbdulRaqeebKhatri\OneDrive\Documents\Knowledge Base`
Python is invoked via the venv: `scraper\venv\Scripts\python.exe`.

---

## Task 1: Project Setup (idempotent)

**Files:**
- Create/verify: `scraper/requirements.txt`, `scraper/__init__.py`, `scraper/parsers/__init__.py`, `scraper/writers/__init__.py`, `scraper/state/scraped_versions.json`, `tests/fixtures/` dir

- [ ] **Step 1: Ensure folders exist**

Run:
```powershell
New-Item -ItemType Directory -Force "scraper\parsers" | Out-Null
New-Item -ItemType Directory -Force "scraper\writers" | Out-Null
New-Item -ItemType Directory -Force "scraper\state"   | Out-Null
New-Item -ItemType Directory -Force "tests\fixtures"  | Out-Null
```

- [ ] **Step 2: Write `scraper/requirements.txt`**

```
playwright>=1.40.0
beautifulsoup4>=4.12.0
lxml>=4.9.0
pytest>=7.4.0
```

- [ ] **Step 3: Ensure package marker files exist**

Create these three files if missing, each containing a single comment line:

`scraper/__init__.py`:
```python
# Contoso KB scraper package
```
`scraper/parsers/__init__.py`:
```python
# parsers package
```
`scraper/writers/__init__.py`:
```python
# writers package
```

- [ ] **Step 4: Ensure state file exists**

If `scraper/state/scraped_versions.json` does not exist, create it containing exactly:
```json
{}
```
(If it already exists with real data, leave it untouched.)

- [ ] **Step 5: Ensure venv + dependencies**

```powershell
if (-not (Test-Path "scraper\venv\Scripts\python.exe")) { python -m venv scraper\venv }
scraper\venv\Scripts\python.exe -m pip install -r scraper\requirements.txt
scraper\venv\Scripts\python.exe -m playwright install chromium
```

- [ ] **Step 6: Verify imports**

```powershell
scraper\venv\Scripts\python.exe -c "from playwright.sync_api import sync_playwright; from bs4 import BeautifulSoup; print('deps OK')"
```
Expected: `deps OK`

---

## Task 2: Capture Real Fixtures

**Files:**
- Create: `tests/capture_fixtures.py`
- Produces: `tests/fixtures/{tradedesk,web4,saleshub}_real.html` and `..._rest.json`

These fixtures are captured once from the live site (reachable from this whitelisted machine) and then committed as static test inputs. All later tests read them with no network.

- [ ] **Step 1: Create `tests/capture_fixtures.py`**

```python
"""
One-time capture of real fixtures from help.contoso.example.
Run from the Knowledge Base root:
  scraper\\venv\\Scripts\\python.exe tests\\capture_fixtures.py
Saves real HTML pages and REST API responses into tests/fixtures/.
"""
import json
import urllib.request
from pathlib import Path

BASE = "https://help.contoso.example"
FIXTURES = Path(__file__).parent / "fixtures"

PAGES = {
    "tradedesk_real.html": f"{BASE}/display/releasenotes/Version+3.0.1.9",
    "web4_real.html":     f"{BASE}/display/ReleaseNotesWeb4/Version+4.0.3.0",
    "saleshub_real.html":  f"{BASE}/display/SHReleaseNotes/SalesHub+WEB+Version+2.0.2.1",
}
REST = {
    "tradedesk_rest.json": "releasenotes",
    "web4_rest.json":     "ReleaseNotesWeb4",
    "saleshub_rest.json":  "SHReleaseNotes",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 fixture-capture"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main():
    FIXTURES.mkdir(parents=True, exist_ok=True)

    for name, url in PAGES.items():
        print(f"Fetching page {url}")
        (FIXTURES / name).write_bytes(fetch(url))

    for name, space_key in REST.items():
        # Capture ALL pages (follow _links.next) into one combined results list,
        # mimicking what discovery will iterate over.
        combined = {"results": []}
        next_path = f"/rest/api/content?spaceKey={space_key}&type=page&limit=100&start=0"
        while next_path:
            data = json.loads(fetch(f"{BASE}{next_path}"))
            combined["results"].extend(data.get("results", []))
            nxt = data.get("_links", {}).get("next")
            next_path = nxt if nxt else None
        print(f"REST {space_key}: {len(combined['results'])} pages")
        (FIXTURES / name).write_text(json.dumps(combined, indent=2), encoding="utf-8")

    print("Fixtures captured.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the capture**

```powershell
scraper\venv\Scripts\python.exe tests\capture_fixtures.py
```
Expected (counts are the total pages in each space, which include the index page and any non-version pages):
```
REST releasenotes: 119 pages
REST ReleaseNotesWeb4: 20 pages
REST SHReleaseNotes: 23 pages
Fixtures captured.
```

- [ ] **Step 3: Verify fixtures exist and are non-trivial**

```powershell
Get-ChildItem tests\fixtures | Select-Object Name, Length
```
Expected: six files; the `*_real.html` files are tens of KB; the `*_rest.json` files contain a `results` array.

---

## Task 3: config.py (V2)

**Files:**
- Create (overwrite): `scraper/config.py`

- [ ] **Step 1: Write `scraper/config.py`**

```python
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent.parent           # Knowledge Base/
LIBRARY_BASE = BASE_DIR / "library"
STATE_DIR    = Path(__file__).parent / "state"
STATE_FILE   = STATE_DIR / "scraped_versions.json"
LOG_FILE     = STATE_DIR / "run.log"
REPORT_FILE  = STATE_DIR / "last_run_report.json"

BASE_URL = "https://help.contoso.example"

# ── Products ──────────────────────────────────────────────────────────────────
# space_key values verified live on 2026-05-27. release_notes_url is derived as
# f"{BASE_URL}/display/{space_key}". The --discover command can re-derive and
# rewrite release_notes_url robustly, but these defaults work out of the box.
PRODUCTS: dict[str, dict] = {
    "tradedesk": {
        "display_name": "TradeDesk",
        "space_key": "releasenotes",
        "release_notes_url": "https://help.contoso.example/display/releasenotes",
        "section_aliases": {
            "enhancements": ["enhancements and new features", "enhancements", "new features"],
            "bugs": ["bugs", "bug fixes"],
            "schema_changes": ["schema changes", "database changes"],
            "tasks": ["tasks"],
        },
    },
    "web4": {
        "display_name": "Web4",
        "space_key": "ReleaseNotesWeb4",
        "release_notes_url": "https://help.contoso.example/display/ReleaseNotesWeb4",
        "section_aliases": {
            "enhancements": ["enhancements and new features", "enhancements", "new features"],
            "bugs": ["bugs", "bug fixes"],
            "schema_changes": ["schema changes", "database changes"],
            "tasks": ["tasks"],
        },
    },
    "saleshub": {
        "display_name": "SalesHub",
        "space_key": "SHReleaseNotes",
        "release_notes_url": "https://help.contoso.example/display/SHReleaseNotes",
        "section_aliases": {
            "enhancements": ["enhancements and new features", "enhancements", "new features"],
            "bugs": ["bugs", "bug fixes"],
            "schema_changes": ["schema changes", "database changes"],
            "tasks": ["tasks"],
        },
    },
}

# Canonical column normalization for release-note tables.
# Keys are lowercased, whitespace-collapsed header text. The Risk column header
# is a long blob beginning "risk assessment" and is matched by prefix in code.
COLUMN_SYNONYMS: dict[str, str] = {
    "sr. #": "sno", "sr #": "sno", "sr.#": "sno", "s.no": "sno", "sno": "sno", "#": "sno", "no": "sno",
    "task id": "id", "tfs/portal id": "id", "portal/tfs id": "id", "tfs id": "id", "portal id": "id", "id": "id",
    "module": "module",
    "new feature/ improvement of current feature": "feature_type",
    "prerequisites": "prerequisites",
    "details": "details", "description": "details",
    "configuration changes": "config_changes",
    "key feature": "key_feature", "key features": "key_feature",
    "is there a change to previous behavior?": "behavior_change",
    "is there a change to previous behaviour?": "behavior_change",
    "is this feature 'on' by default?": "on_by_default",
}
```

- [ ] **Step 2: Verify it imports and exposes the expected values**

```powershell
scraper\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from scraper.config import PRODUCTS, COLUMN_SYNONYMS, LIBRARY_BASE; print(len(PRODUCTS), 'products'); print([p['space_key'] for p in PRODUCTS.values()]); print('synonyms', len(COLUMN_SYNONYMS))"
```
Expected:
```
3 products
['releasenotes', 'ReleaseNotesWeb4', 'SHReleaseNotes']
synonyms 24
```

---

## Task 4: discovery.py (TDD)

**Files:**
- Create: `tests/test_discovery.py`
- Create: `scraper/discovery.py`

`discovery.py` turns a space key into a clean list of version pages. HTTP is injected so tests use the captured `*_rest.json` fixtures with no network.

- [ ] **Step 1: Write failing tests `tests/test_discovery.py`**

```python
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.discovery import extract_version, is_version_title, discover_versions

FIX = Path(__file__).parent / "fixtures"


def make_http_get(rest_file: str):
    """Return an http_get(url) that serves the captured combined fixture once,
    then signals no further pages (so the pagination loop terminates)."""
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
```

- [ ] **Step 2: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_discovery.py -v 2>&1 | Select-Object -First 15
```
Expected: `ModuleNotFoundError: No module named 'scraper.discovery'`

- [ ] **Step 3: Create `scraper/discovery.py`**

```python
from __future__ import annotations
import json
import re
import urllib.request
from typing import Callable, Optional

from scraper.config import BASE_URL

# Two or more dot-separated number groups => a real version (e.g. 2.0.2.1, 3.0.1.9).
# "Web 4.0" (single dot) is intentionally excluded.
_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)+")


def extract_version(title: str) -> Optional[str]:
    m = _VERSION_RE.search(title or "")
    return m.group(0) if m else None


def is_version_title(title: str) -> bool:
    return extract_version(title) is not None


def default_http_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 kb-scraper"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _unique_version(title: str, m: re.Match, taken: set[str], idx: int) -> str:
    """Return a version string unique within `taken`. The base is the numeric
    match; on collision (e.g. 'Version 2.4.0.10' vs '...2.4.0.10 EXT') append a
    slug of the title's trailing text, or the page index as a last resort."""
    base = m.group(0)
    if base not in taken:
        return base
    tail = title[m.end():].strip()
    suffix = re.sub(r"[^A-Za-z0-9]+", "-", tail).strip("-") or str(idx)
    candidate = f"{base}-{suffix}"
    while candidate in taken:
        candidate = f"{base}-{suffix}-{idx}"
        idx += 1
    return candidate


def discover_versions(space_key: str, http_get: Callable[[str], dict] = default_http_get) -> list[dict]:
    """
    Return a clean, de-duplicated list of version pages for a Confluence space:
      [{"version": "2.0.2.1", "title": "...", "url": "https://...", "page_id": "123"}, ...]
    Follows _links.next pagination until exhausted. Version strings are made
    unique so distinct pages never share a filename.
    """
    results: list[dict] = []
    seen_urls: set[str] = set()
    taken_versions: set[str] = set()
    next_path = f"/rest/api/content?spaceKey={space_key}&type=page&limit=100&start=0"
    idx = 0

    while next_path:
        url = next_path if next_path.startswith("http") else f"{BASE_URL}{next_path}"
        data = http_get(url)
        for item in data.get("results", []):
            idx += 1
            title = item.get("title", "")
            m = _VERSION_RE.search(title)
            if not m:
                continue
            webui = (item.get("_links", {}) or {}).get("webui", "")
            full_url = webui if webui.startswith("http") else f"{BASE_URL}{webui}"
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            version = _unique_version(title, m, taken_versions, idx)
            taken_versions.add(version)
            results.append({
                "version": version,
                "title": title,
                "url": full_url,
                "page_id": str(item.get("id", "")),
            })
        next_path = (data.get("_links", {}) or {}).get("next")

    return results
```

- [ ] **Step 4: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_discovery.py -v
```
Expected: all green (12 tests).

---

## Task 5: parsers/universal.py (TDD rewrite)

**Files:**
- Create: `tests/test_universal_parser.py`
- Create (overwrite): `scraper/parsers/universal.py`

- [ ] **Step 1: Write failing tests `tests/test_universal_parser.py`**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.parsers.universal import parse_page, normalize_header, _extract_version
from scraper.config import COLUMN_SYNONYMS

FIX = Path(__file__).parent / "fixtures"
ALIASES = {
    "enhancements": ["enhancements and new features", "enhancements", "new features"],
    "bugs": ["bugs", "bug fixes"],
    "schema_changes": ["schema changes", "database changes"],
    "tasks": ["tasks"],
}


def html(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def parse(name, product, version, title):
    url = f"http://example/{version}"
    return parse_page(html(name), product, version, title, url, "shot.png", ALIASES, COLUMN_SYNONYMS)


# normalize_header
def test_normalize_known_synonym():
    assert normalize_header("S.No", COLUMN_SYNONYMS) == "sno"

def test_normalize_tfs_id_variants():
    assert normalize_header("TFS/Portal ID", COLUMN_SYNONYMS) == "id"
    assert normalize_header("Portal/TFS ID", COLUMN_SYNONYMS) == "id"
    assert normalize_header("Task ID", COLUMN_SYNONYMS) == "id"

def test_normalize_risk_blob_prefix():
    blob = "Risk assessment: High: Requires a high degree of actionMedium: ...Low: ..."
    assert normalize_header(blob, COLUMN_SYNONYMS) == "risk"

def test_normalize_unknown_is_slugified():
    assert normalize_header("Object Type", COLUMN_SYNONYMS) == "object_type"
    assert normalize_header("Action Type", COLUMN_SYNONYMS) == "action_type"


# _extract_version
def test_extract_version_from_title():
    assert _extract_version("SalesHub WEB Version 2.0.2.1") == "2.0.2.1"


# SalesHub real page
def test_saleshub_sections_present():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    assert "enhancements" in r and "bugs" in r and "schema_changes" in r

def test_saleshub_row_counts():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    assert len(r["enhancements"]) == 8
    assert len(r["bugs"]) == 3
    assert len(r["schema_changes"]) == 1

def test_saleshub_first_enhancement_id():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    assert r["enhancements"][0]["id"] == "57196"
    assert r["enhancements"][0]["risk"] == "LOW"

def test_saleshub_schema_columns_preserved():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    row = r["schema_changes"][0]
    assert row["object_type"] == "Table"
    assert row["object_name"] == "WEB_FTF_DETAIL"
    assert row["action_type"] == "Altered"

def test_saleshub_ignores_table_of_contents():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    assert "table_of_contents" not in r and "tasks" not in r


# Web4 real page
def test_web4_tasks_and_schema_only():
    r = parse("web4_real.html", "web4", "4.0.3.0", "Version 4.0.3.0")
    assert "tasks" in r and "schema_changes" in r
    assert "enhancements" not in r and "bugs" not in r

def test_web4_row_counts():
    r = parse("web4_real.html", "web4", "4.0.3.0", "Version 4.0.3.0")
    assert len(r["tasks"]) == 4
    assert len(r["schema_changes"]) == 29

def test_web4_first_task_id():
    r = parse("web4_real.html", "web4", "4.0.3.0", "Version 4.0.3.0")
    assert r["tasks"][0]["id"] == "71669"


# TradeDesk real page
def test_tradedesk_row_counts():
    r = parse("tradedesk_real.html", "tradedesk", "3.0.1.9", "Version 3.0.1.9")
    assert len(r["enhancements"]) == 9
    assert len(r["bugs"]) == 3
    assert len(r["schema_changes"]) == 9

def test_tradedesk_module_column_captured():
    r = parse("tradedesk_real.html", "tradedesk", "3.0.1.9", "Version 3.0.1.9")
    assert r["enhancements"][0]["id"] == "14093"
    assert r["enhancements"][0]["module"] == "Dashboard Activity"


# Metadata
def test_metadata_fields():
    r = parse("saleshub_real.html", "saleshub", "2.0.2.1", "SalesHub WEB Version 2.0.2.1")
    assert r["product"] == "saleshub"
    assert r["version"] == "2.0.2.1"
    assert r["title"] == "SalesHub WEB Version 2.0.2.1"
    assert r["screenshot"] == "shot.png"
    assert "scraped_at" in r and r["url"].endswith("2.0.2.1")
```

- [ ] **Step 2: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_universal_parser.py -v 2>&1 | Select-Object -First 15
```
Expected: import error / function not defined.

- [ ] **Step 3: Create `scraper/parsers/universal.py`**

```python
from __future__ import annotations
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup, Tag

_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)+")
_HEADINGS = ("h1", "h2", "h3", "h4")


def _extract_version(title: str) -> Optional[str]:
    m = _VERSION_RE.search(title or "")
    return m.group(0) if m else None


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "col"


def normalize_header(header: str, synonyms: dict[str, str]) -> str:
    key = _collapse_ws(header).lower()
    if key.startswith("risk assessment"):
        return "risk"
    if key in synonyms:
        return synonyms[key]
    return _slugify(key)


def _find_content(soup: BeautifulSoup) -> Tag:
    for selector in ["#main-content", ".wiki-content", "#content", "main", "article"]:
        el = soup.select_one(selector)
        if el:
            return el
    return soup


def _table_after(heading: Tag) -> Optional[Tag]:
    """Walk siblings after a heading until the next heading; return the first
    table that is either a sibling or nested inside a sibling (Confluence wraps
    tables in div.table-wrap)."""
    node = heading.next_sibling
    while node is not None:
        if isinstance(node, Tag):
            if node.name in _HEADINGS:
                return None
            if node.name == "table":
                return node
            inner = node.find("table")
            if inner:
                return inner
        node = node.next_sibling
    return None


def _parse_table(table: Tag, synonyms: dict[str, str]) -> list[dict]:
    rows = table.find_all("tr")
    if len(rows) < 2:
        return []
    headers = [normalize_header(c.get_text(separator=" ", strip=True), synonyms)
               for c in rows[0].find_all(["th", "td"])]
    out: list[dict] = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        row: dict = {}
        for i, cell in enumerate(cells):
            if i < len(headers):
                row[headers[i]] = _collapse_ws(cell.get_text(separator=" ", strip=True))
        if any(v for v in row.values()):
            out.append(row)
    return out


def _resolve_section(heading_text: str, section_aliases: dict[str, list[str]]) -> Optional[str]:
    text = _collapse_ws(heading_text).lower()
    for canonical, aliases in section_aliases.items():
        if any(alias == text or alias in text for alias in aliases):
            return canonical
    return None


def parse_page(
    html: str,
    product: str,
    version: str,
    title: str,
    url: str,
    screenshot_path: str,
    section_aliases: dict[str, list[str]],
    column_synonyms: dict[str, str],
) -> dict:
    soup = BeautifulSoup(html, "lxml")
    content = _find_content(soup)

    result: dict = {
        "product": product,
        "version": version,
        "title": title,
        "url": url,
        "scraped_at": datetime.now().isoformat(),
        "screenshot": screenshot_path,
    }

    for heading in content.find_all(list(_HEADINGS)):
        heading_text = heading.get_text(separator=" ", strip=True)
        if "table of contents" in heading_text.lower():
            continue
        section = _resolve_section(heading_text, section_aliases)
        if not section or section in result:
            continue
        table = _table_after(heading)
        if not table:
            continue
        rows = _parse_table(table, column_synonyms)
        if rows:
            result[section] = rows

    return result
```

- [ ] **Step 4: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_universal_parser.py -v
```
Expected: all green.

Note on `_resolve_section`: aliases are matched by exact-or-substring against the lowercased heading. "tasks" matches "Tasks"; "enhancements" matches "Enhancements and New Features"; "bugs" matches "Bugs". Schema headings match "schema changes". The first matching canonical section wins and is not overwritten.

---

## Task 6: writers/json_writer.py (TDD)

**Files:**
- Create: `tests/test_json_writer.py`
- Create (overwrite): `scraper/writers/json_writer.py`

- [ ] **Step 1: Write failing tests `tests/test_json_writer.py`**

```python
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.writers.json_writer import save_version

SAMPLE = {
    "product": "saleshub", "version": "2.0.2.1", "title": "SalesHub WEB Version 2.0.2.1",
    "url": "http://x", "scraped_at": "2026-05-27T10:00:00", "screenshot": "s.png",
    "enhancements": [{"sno": "1", "id": "57196", "details": "IBAN", "risk": "LOW"}],
    "schema_changes": [{"object_type": "Table", "object_name": "WEB_FTF_DETAIL", "action_type": "Altered"}],
}


def test_creates_json_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(SAMPLE, Path(tmp))
        assert path.exists() and path.suffix == ".json"

def test_path_uses_product_and_version():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(SAMPLE, Path(tmp))
        assert "saleshub" in str(path) and "versions" in str(path) and path.name == "2.0.2.1.json"

def test_content_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(SAMPLE, Path(tmp))
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["enhancements"][0]["id"] == "57196"
        assert loaded["schema_changes"][0]["object_name"] == "WEB_FTF_DETAIL"

def test_slash_in_version_becomes_dash():
    data = {**SAMPLE, "version": "2.0/EXT"}
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(data, Path(tmp))
        assert "/" not in path.name and path.name == "2.0-EXT.json"
```

- [ ] **Step 2: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_json_writer.py -v 2>&1 | Select-Object -First 10
```

- [ ] **Step 3: Create `scraper/writers/json_writer.py`**

```python
from __future__ import annotations
import json
from pathlib import Path


def safe_name(version: str) -> str:
    return version.replace(" ", "_").replace("/", "-").strip()


def save_version(data: dict, library_base: Path) -> Path:
    output_dir = library_base / data["product"] / "versions"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_name(data['version'])}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return output_path
```

- [ ] **Step 4: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_json_writer.py -v
```

---

## Task 7: writers/md_writer.py (TDD rewrite)

**Files:**
- Create: `tests/test_md_writer.py`
- Create (overwrite): `scraper/writers/md_writer.py`

Each present section renders as a Markdown table whose columns come from the union of keys across that section's rows (stable order: first-seen).

- [ ] **Step 1: Write failing tests `tests/test_md_writer.py`**

```python
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.writers.md_writer import save_version, render_md

DATA = {
    "product": "saleshub", "version": "2.0.2.1", "title": "SalesHub WEB Version 2.0.2.1",
    "url": "http://x", "scraped_at": "2026-05-27T10:00:00", "screenshot": "s.png",
    "enhancements": [
        {"sno": "1", "id": "57196", "details": "IBAN Validation", "risk": "LOW"},
        {"sno": "2", "id": "57200", "details": "Other", "risk": "LOW", "module": "X"},
    ],
    "schema_changes": [{"object_type": "Table", "object_name": "WEB_FTF_DETAIL", "action_type": "Altered"}],
}


def test_renders_title_and_version():
    md = render_md(DATA)
    assert "2.0.2.1" in md and "SalesHub WEB Version 2.0.2.1" in md

def test_renders_section_heading():
    md = render_md(DATA)
    assert "Enhancements" in md and "Schema Changes" in md

def test_renders_table_values():
    md = render_md(DATA)
    assert "57196" in md and "IBAN Validation" in md and "WEB_FTF_DETAIL" in md

def test_table_has_union_of_columns():
    # second enhancement row adds "module" -> column must appear in header
    md = render_md(DATA)
    assert "module" in md

def test_omits_absent_sections():
    md = render_md(DATA)
    assert "Bugs" not in md and "Tasks" not in md

def test_save_creates_md_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = save_version(DATA, Path(tmp))
        assert path.exists() and path.name == "2.0.2.1.md"
```

- [ ] **Step 2: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_md_writer.py -v 2>&1 | Select-Object -First 10
```

- [ ] **Step 3: Create `scraper/writers/md_writer.py`**

```python
from __future__ import annotations
from pathlib import Path

# Canonical section -> Markdown heading
_SECTION_TITLES = {
    "enhancements": "Enhancements and New Features",
    "bugs": "Bugs",
    "schema_changes": "Schema Changes",
    "tasks": "Tasks",
}
_SECTION_ORDER = ["enhancements", "tasks", "bugs", "schema_changes"]


def safe_name(version: str) -> str:
    return version.replace(" ", "_").replace("/", "-").strip()


def _columns_for(rows: list[dict]) -> list[str]:
    cols: list[str] = []
    for row in rows:
        for k in row:
            if k not in cols:
                cols.append(k)
    return cols


def _escape(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _render_section(name: str, rows: list[dict]) -> list[str]:
    cols = _columns_for(rows)
    lines = [f"## {_SECTION_TITLES.get(name, name.title())}", ""]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(_escape(row.get(c, "")) for c in cols) + " |")
    lines.append("")
    return lines


def render_md(data: dict) -> str:
    display = data["product"].replace("_", " ").title()
    lines = [
        f"# {display} — {data.get('title', 'Version ' + data['version'])}",
        "",
        f"**Version:** {data['version']}  ",
        f"**URL:** {data['url']}  ",
        f"**Scraped:** {data['scraped_at']}  ",
        f"**Screenshot:** `{data.get('screenshot', '')}`",
        "",
    ]
    for name in _SECTION_ORDER:
        rows = data.get(name)
        if rows:
            lines += _render_section(name, rows)
    return "\n".join(lines)


def save_version(data: dict, library_base: Path) -> Path:
    output_dir = library_base / data["product"] / "versions"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{safe_name(data['version'])}.md"
    output_path.write_text(render_md(data), encoding="utf-8")
    return output_path
```

- [ ] **Step 4: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_md_writer.py -v
```

---

## Task 8: writers/index_generator.py (TDD rewrite)

**Files:**
- Create: `tests/test_index_generator.py`
- Create (overwrite): `scraper/writers/index_generator.py`

- [ ] **Step 1: Write failing tests `tests/test_index_generator.py`**

```python
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.writers.index_generator import generate_all

PRODUCTS = {
    "tradedesk": {"display_name": "TradeDesk"},
    "web4": {"display_name": "Web4"},
    "saleshub": {"display_name": "SalesHub"},
}
V1 = {
    "product": "tradedesk", "version": "3.0.1.9", "title": "Version 3.0.1.9",
    "url": "http://x/3.0.1.9", "scraped_at": "2026-05-27T10:00:00", "screenshot": "",
    "enhancements": [{"id": "14093", "details": "Dashboard Activity"}],
    "bugs": [{"id": "14081", "details": "F10 key bug"}],
}
V2 = {
    "product": "tradedesk", "version": "3.0.1.8", "title": "Version 3.0.1.8",
    "url": "http://x/3.0.1.8", "scraped_at": "2026-05-27T09:00:00", "screenshot": "",
    "enhancements": [{"id": "13000", "details": "Earlier feature"}],
}
W1 = {
    "product": "web4", "version": "4.0.3.0", "title": "Version 4.0.3.0",
    "url": "http://x/4.0.3.0", "scraped_at": "2026-05-27T10:00:00", "screenshot": "",
    "tasks": [{"id": "71669", "details": "Quick Pay"}],
}


def write(lib, items):
    for v in items:
        d = lib / v["product"] / "versions"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{v['version']}.json").write_text(json.dumps(v), encoding="utf-8")


def test_changelog_lists_versions_newest_first():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp); write(lib, [V1, V2]); generate_all(lib, PRODUCTS)
        text = (lib / "tradedesk" / "CHANGELOG.md").read_text(encoding="utf-8")
        assert text.index("3.0.1.9") < text.index("3.0.1.8")

def test_features_list_includes_enhancements_and_tasks():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp); write(lib, [V1, W1]); generate_all(lib, PRODUCTS)
        fx = (lib / "tradedesk" / "features-list.md").read_text(encoding="utf-8")
        w4 = (lib / "web4" / "features-list.md").read_text(encoding="utf-8")
        assert "Dashboard Activity" in fx
        assert "Quick Pay" in w4   # tasks appear in features list

def test_bugs_list_includes_bugs():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp); write(lib, [V1]); generate_all(lib, PRODUCTS)
        text = (lib / "tradedesk" / "bugs-list.md").read_text(encoding="utf-8")
        assert "F10 key bug" in text

def test_master_index_lists_all_products_with_counts():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp); write(lib, [V1, V2, W1]); generate_all(lib, PRODUCTS)
        idx = (lib / "INDEX.md").read_text(encoding="utf-8")
        assert "TradeDesk" in idx and "Web4" in idx and "SalesHub" in idx
        assert "2 version" in idx  # tradedesk has 2

def test_empty_products_do_not_raise():
    with tempfile.TemporaryDirectory() as tmp:
        lib = Path(tmp); generate_all(lib, PRODUCTS)
        assert (lib / "INDEX.md").exists()
```

- [ ] **Step 2: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_index_generator.py -v 2>&1 | Select-Object -First 10
```

- [ ] **Step 3: Create `scraper/writers/index_generator.py`**

```python
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path

# Sections counted/listed as "features"
_FEATURE_SECTIONS = ["enhancements", "tasks"]


def _safe(version: str) -> str:
    return version.replace(" ", "_").replace("/", "-").strip()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _load_versions(library_base: Path, product: str) -> list[dict]:
    vdir = library_base / product / "versions"
    if not vdir.exists():
        return []
    out = []
    for f in vdir.glob("*.json"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    # newest-first by version tuple when numeric, else string
    def key(v):
        parts = v.get("version", "").replace("-", ".").split(".")
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            return (v.get("version", ""),)
    return sorted(out, key=key, reverse=True)


def _row_line(row: dict) -> str:
    ident = row.get("id")
    details = row.get("details") or next((v for v in row.values() if v), "")
    return f"- **{ident}** — {details}" if ident else f"- {details}"


def _generate_product(library_base: Path, product: str, display: str):
    versions = _load_versions(library_base, product)
    pdir = library_base / product
    pdir.mkdir(parents=True, exist_ok=True)

    # CHANGELOG
    lines = [f"# {display} — Changelog", "", f"*Generated: {_now()}*", "", "---", ""]
    for v in versions:
        parts = []
        for sec, label in [("enhancements", "enhancement"), ("tasks", "task"),
                           ("bugs", "bug fix"), ("schema_changes", "schema change")]:
            n = len(v.get(sec, []))
            if n:
                parts.append(f"{n} {label}(s)")
        summary = ", ".join(parts) if parts else "no items extracted"
        lines += [f"## {v['version']}", "", f"*{v['url']}*", "",
                  f"**Summary:** {summary}", "",
                  f"[Details](versions/{_safe(v['version'])}.md)", "", "---", ""]
    (pdir / "CHANGELOG.md").write_text("\n".join(lines), encoding="utf-8")

    # features-list (enhancements + tasks)
    lines = [f"# {display} — All Features & Enhancements", "", f"*Generated: {_now()}*", "", "---", ""]
    for v in versions:
        rows = [r for sec in _FEATURE_SECTIONS for r in v.get(sec, [])]
        if rows:
            lines += [f"## {v['version']}", ""]
            lines += [_row_line(r) for r in rows]
            lines.append("")
    (pdir / "features-list.md").write_text("\n".join(lines), encoding="utf-8")

    # bugs-list
    lines = [f"# {display} — All Bug Fixes", "", f"*Generated: {_now()}*", "", "---", ""]
    for v in versions:
        rows = v.get("bugs", [])
        if rows:
            lines += [f"## {v['version']}", ""]
            lines += [_row_line(r) for r in rows]
            lines.append("")
    (pdir / "bugs-list.md").write_text("\n".join(lines), encoding="utf-8")


def _generate_master(library_base: Path, products: dict):
    lines = ["# Contoso Knowledge Base — Release Notes Library", "",
             f"*Generated: {_now()}*", "", "---", ""]
    for key, cfg in products.items():
        versions = _load_versions(library_base, key)
        lines += [f"## {cfg['display_name']}", "",
                  f"**{len(versions)} version(s) scraped**", "",
                  f"- [Changelog]({key}/CHANGELOG.md)",
                  f"- [All Features]({key}/features-list.md)",
                  f"- [All Bugs]({key}/bugs-list.md)", ""]
        for v in versions[:10]:
            lines.append(f"- [{v['version']}]({key}/versions/{_safe(v['version'])}.md)")
        if len(versions) > 10:
            lines.append(f"- *...and {len(versions) - 10} more (see Changelog)*")
        lines += ["", "---", ""]
    library_base.mkdir(parents=True, exist_ok=True)
    (library_base / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")


def generate_all(library_base: Path, products: dict):
    for key, cfg in products.items():
        _generate_product(library_base, key, cfg["display_name"])
    _generate_master(library_base, products)
```

- [ ] **Step 4: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_index_generator.py -v
```

---

## Task 9: core.py — Browser (retries) + StateTracker

**Files:**
- Create (overwrite): `scraper/core.py`

- [ ] **Step 1: Write `scraper/core.py`**

```python
from __future__ import annotations
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, Browser as PWBrowser

log = logging.getLogger("scraper")


class Browser:
    """Headed Chrome wrapper. Used only to render version pages and screenshot."""

    def __init__(self, headless: bool = False, timeout_ms: int = 30_000, retries: int = 3):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.retries = retries
        self._pw = None
        self._browser: Optional[PWBrowser] = None
        self._page: Optional[Page] = None

    def open(self) -> "Browser":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless, channel="chrome")
        self._page = self._browser.new_page()
        return self

    def close(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def __enter__(self) -> "Browser":
        return self.open()

    def __exit__(self, *_):
        self.close()

    def navigate(self, url: str):
        last_exc = None
        for attempt in range(1, self.retries + 1):
            try:
                self._page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
                return
            except Exception as exc:
                last_exc = exc
                log.warning("navigate attempt %d/%d failed for %s: %s",
                            attempt, self.retries, url, exc)
                time.sleep(2 ** attempt)
        raise last_exc

    def expand_confluence_macros(self):
        for selector in [".expand-control", "[data-macro-name='expand'] .expand-control-text",
                         ".aui-expander-trigger", "a.expand-control"]:
            try:
                for btn in self._page.locator(selector).all():
                    try:
                        btn.click(timeout=1_000)
                        self._page.wait_for_timeout(150)
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
    """Tracks scraped versions for incremental runs."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._state = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def is_scraped(self, product: str, version: str) -> bool:
        return version in self._state.get(product, {})

    def mark_scraped(self, product: str, version: str, url: str):
        self._state.setdefault(product, {})[version] = {
            "url": url, "scraped_at": datetime.now().isoformat(),
        }
        self._save()

    def get_scraped_versions(self, product: str) -> dict:
        return self._state.get(product, {})
```

- [ ] **Step 2: Verify import**

```powershell
scraper\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from scraper.core import Browser, StateTracker; print('core OK')"
```
Expected: `core OK`

---

## Task 10: config rewrite helper + round-trip test (TDD)

**Files:**
- Create: `tests/test_config_roundtrip.py`
- Create: `scraper/config_writer.py`

This isolates the V1 silent-failure bug: a tested, verified mechanism to rewrite `release_notes_url` values in `config.py`.

- [ ] **Step 1: Write failing tests `tests/test_config_roundtrip.py`**

```python
import sys, importlib.util
from pathlib import Path
import tempfile
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.config_writer import update_release_notes_urls

CONFIG_TEMPLATE = '''\
PRODUCTS = {
    "tradedesk": {
        "display_name": "TradeDesk",
        "space_key": "releasenotes",
        "release_notes_url": "",
    },
    "web4": {
        "display_name": "Web4",
        "space_key": "ReleaseNotesWeb4",
        "release_notes_url": "",
    },
}
'''


def _load(path: Path):
    spec = importlib.util.spec_from_file_location("tmp_config", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_update_writes_urls():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.py"
        cfg.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        update_release_notes_urls(cfg, {
            "tradedesk": "https://help.contoso.example/display/releasenotes",
            "web4": "https://help.contoso.example/display/ReleaseNotesWeb4",
        })
        mod = _load(cfg)
        assert mod.PRODUCTS["tradedesk"]["release_notes_url"] == "https://help.contoso.example/display/releasenotes"
        assert mod.PRODUCTS["web4"]["release_notes_url"] == "https://help.contoso.example/display/ReleaseNotesWeb4"


def test_update_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.py"
        cfg.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        urls = {"tradedesk": "https://x/fx", "web4": "https://x/w4"}
        update_release_notes_urls(cfg, urls)
        update_release_notes_urls(cfg, urls)  # second time must not corrupt
        mod = _load(cfg)
        assert mod.PRODUCTS["tradedesk"]["release_notes_url"] == "https://x/fx"
        assert mod.PRODUCTS["web4"]["release_notes_url"] == "https://x/w4"


def test_update_only_touches_named_products():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "config.py"
        cfg.write_text(CONFIG_TEMPLATE, encoding="utf-8")
        update_release_notes_urls(cfg, {"tradedesk": "https://x/fx"})
        mod = _load(cfg)
        assert mod.PRODUCTS["tradedesk"]["release_notes_url"] == "https://x/fx"
        assert mod.PRODUCTS["web4"]["release_notes_url"] == ""  # untouched
```

- [ ] **Step 2: Run — confirm FAIL**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_config_roundtrip.py -v 2>&1 | Select-Object -First 10
```

- [ ] **Step 3: Create `scraper/config_writer.py`**

```python
from __future__ import annotations
import re
from pathlib import Path


def update_release_notes_urls(config_path: Path, resolved: dict[str, str]) -> None:
    """
    Robustly set each product's release_notes_url in config.py.
    For each product key, replaces the FIRST "release_notes_url": "..." that
    appears after that product key, anchored on the key so blocks don't bleed.
    """
    text = config_path.read_text(encoding="utf-8")
    for product_key, url in resolved.items():
        pattern = re.compile(
            r'("' + re.escape(product_key) + r'"\s*:\s*\{.*?"release_notes_url"\s*:\s*)"[^"]*"',
            re.DOTALL,
        )
        replacement = r'\1"' + url.replace("\\", "\\\\") + '"'
        text, n = pattern.subn(replacement, text, count=1)
        if n == 0:
            raise ValueError(f"Could not locate release_notes_url for product '{product_key}'")
    config_path.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Run — confirm PASS**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/test_config_roundtrip.py -v
```

---

## Task 11: run.py — Orchestrator

**Files:**
- Create (overwrite): `scraper/run.py`

- [ ] **Step 1: Write `scraper/run.py`**

```python
"""
Contoso KB Scraper V2 — orchestrator.
  python scraper/run.py --all
  python scraper/run.py --product tradedesk [--force]
  python scraper/run.py --index-only
  python scraper/run.py --validate     (dry-run: check space keys, no scraping)
  python scraper/run.py --discover      (re-derive + rewrite release_notes_url in config.py)
"""
from __future__ import annotations
import sys
import json
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.config import (PRODUCTS, LIBRARY_BASE, STATE_FILE, LOG_FILE, REPORT_FILE, BASE_URL)
from scraper.core import Browser, StateTracker
from scraper.discovery import discover_versions, default_http_get
from scraper.parsers.universal import parse_page
from scraper.writers import json_writer, md_writer, index_generator
from scraper.config_writer import update_release_notes_urls
from scraper import config as config_module

log = logging.getLogger("scraper")


def _setup_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(LOG_FILE, encoding="utf-8")],
    )


def scrape_product(product_key: str, force: bool, report: dict):
    cfg = PRODUCTS[product_key]
    tracker = StateTracker(STATE_FILE)
    log.info("=== %s ===", cfg["display_name"])

    versions = discover_versions(cfg["space_key"])
    log.info("%s: discovered %d version page(s)", product_key, len(versions))
    stats = {"discovered": len(versions), "new": 0, "skipped": 0, "failed": 0, "failed_urls": []}

    with Browser() as browser:
        for v in versions:
            ver, url, title = v["version"], v["url"], v["title"]
            if not force and tracker.is_scraped(product_key, ver):
                stats["skipped"] += 1
                continue
            try:
                browser.navigate(url)
                browser.expand_confluence_macros()
                shot = str(LIBRARY_BASE / product_key / "versions" / "screenshots"
                           / f"{json_writer.safe_name(ver)}.png")
                browser.screenshot(shot)
                data = parse_page(browser.get_content(), product_key, ver, title, url, shot,
                                  cfg["section_aliases"], config_module.COLUMN_SYNONYMS)
                json_writer.save_version(data, LIBRARY_BASE)
                md_writer.save_version(data, LIBRARY_BASE)
                tracker.mark_scraped(product_key, ver, url)
                stats["new"] += 1
                log.info("[OK] %s (%s)", ver,
                         ", ".join(f"{k}={len(data[k])}" for k in
                                   ("enhancements", "bugs", "tasks", "schema_changes") if k in data) or "no sections")
            except Exception as exc:
                stats["failed"] += 1
                stats["failed_urls"].append(url)
                log.error("[FAIL] %s: %s", ver, exc)

    report[product_key] = stats
    log.info("%s done: new=%d skipped=%d failed=%d",
             product_key, stats["new"], stats["skipped"], stats["failed"])


def rebuild_indexes():
    log.info("Rebuilding indexes...")
    index_generator.generate_all(LIBRARY_BASE, PRODUCTS)
    log.info("Indexes written to %s", LIBRARY_BASE)


def validate():
    log.info("Validating space keys (dry-run, no scraping)...")
    ok = True
    for key, cfg in PRODUCTS.items():
        try:
            items = discover_versions(cfg["space_key"])
            log.info("  %s [%s]: %d versions", key, cfg["space_key"], len(items))
            if not items:
                ok = False
        except Exception as exc:
            ok = False
            log.error("  %s [%s]: ERROR %s", key, cfg["space_key"], exc)
    log.info("Validation %s", "PASSED" if ok else "FAILED")
    return ok


def discover_and_update_config():
    log.info("Re-deriving release_notes_url for each product...")
    resolved = {}
    for key, cfg in PRODUCTS.items():
        items = discover_versions(cfg["space_key"])
        if items:
            resolved[key] = f"{BASE_URL}/display/{cfg['space_key']}"
            log.info("  %s: %d versions -> %s", key, len(items), resolved[key])
        else:
            log.warning("  %s: no versions found; leaving config unchanged", key)
    if resolved:
        config_path = Path(config_module.__file__)
        update_release_notes_urls(config_path, resolved)
        # Verify by re-import in a subprocess-free way: re-read + exec check
        import importlib
        importlib.reload(config_module)
        for key, url in resolved.items():
            assert config_module.PRODUCTS[key]["release_notes_url"] == url, \
                f"config write verification failed for {key}"
        log.info("config.py updated and verified.")


def write_report(report: dict):
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("Run report written to %s", REPORT_FILE)
    log.info("Summary: %s", {k: {kk: vv for kk, vv in s.items() if kk != "failed_urls"}
                             for k, s in report.items()})


def main():
    parser = argparse.ArgumentParser(description="Contoso KB Release Notes Scraper V2")
    parser.add_argument("--product", choices=list(PRODUCTS.keys()))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--index-only", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--discover", action="store_true")
    args = parser.parse_args()

    _setup_logging()

    if args.validate:
        sys.exit(0 if validate() else 1)
    if args.discover:
        discover_and_update_config()
        return
    if args.index_only:
        rebuild_indexes()
        return

    report: dict = {}
    if args.all:
        for key in PRODUCTS:
            scrape_product(key, args.force, report)
        rebuild_indexes()
        write_report(report)
    elif args.product:
        scrape_product(args.product, args.force, report)
        rebuild_indexes()
        write_report(report)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify help + validate (this one hits the network; the whitelisted machine reaches the REST API)**

```powershell
scraper\venv\Scripts\python.exe scraper\run.py --help
scraper\venv\Scripts\python.exe scraper\run.py --validate
```
Expected: help text prints; then validation logs three products with version counts `117`, `18`, `21` and `Validation PASSED`.

---

## Task 12: Launch.bat — Robust Menu

**Files:**
- Create (overwrite): `scraper/Launch.bat`

- [ ] **Step 1: Write `scraper/Launch.bat`**

```batch
@echo off
setlocal EnableExtensions

REM Always operate from the Knowledge Base root (parent of this script's folder)
pushd "%~dp0.."

set "PY=scraper\venv\Scripts\python.exe"

:MENU
cls
echo.
echo  ============================================
echo    Contoso KB Scraper V2  -  Launch Menu
echo  ============================================
echo.
echo    1.  Scrape ALL products   (incremental)
echo    2.  Scrape TradeDesk only
echo    3.  Scrape Web4 only
echo    4.  Scrape SalesHub only
echo    5.  Force re-scrape ALL   (full refresh)
echo    6.  Validate (dry-run, no scraping)
echo    7.  Discover / refresh URLs in config
echo    8.  Rebuild index files only
echo    9.  One-time setup (venv + dependencies)
echo    0.  Exit
echo.
set "CHOICE="
set /p "CHOICE=  Enter choice [0-9]: "

if "%CHOICE%"=="9" goto SETUP
if "%CHOICE%"=="0" goto END

REM All other options need Python to exist
if not exist "%PY%" (
    echo.
    echo  [ERROR] Python venv not found at %PY%
    echo  Run option 9 (One-time setup) first.
    goto PAUSE_MENU
)

if "%CHOICE%"=="1" ( "%PY%" scraper\run.py --all & goto PAUSE_MENU )
if "%CHOICE%"=="2" ( "%PY%" scraper\run.py --product tradedesk & goto PAUSE_MENU )
if "%CHOICE%"=="3" ( "%PY%" scraper\run.py --product web4 & goto PAUSE_MENU )
if "%CHOICE%"=="4" ( "%PY%" scraper\run.py --product saleshub & goto PAUSE_MENU )
if "%CHOICE%"=="5" ( "%PY%" scraper\run.py --all --force & goto PAUSE_MENU )
if "%CHOICE%"=="6" ( "%PY%" scraper\run.py --validate & goto PAUSE_MENU )
if "%CHOICE%"=="7" ( "%PY%" scraper\run.py --discover & goto PAUSE_MENU )
if "%CHOICE%"=="8" ( "%PY%" scraper\run.py --index-only & goto PAUSE_MENU )

echo  Invalid choice.
goto PAUSE_MENU

:SETUP
echo.
echo  Creating virtual environment and installing dependencies...
if not exist "%PY%" python -m venv scraper\venv
"%PY%" -m pip install -r scraper\requirements.txt
"%PY%" -m playwright install chromium
echo.
echo  Setup complete.
goto PAUSE_MENU

:PAUSE_MENU
echo.
echo  -----------------------------------------
echo   Done. Press any key to return to menu.
echo  -----------------------------------------
pause >nul
goto MENU

:END
popd
endlocal
```

Note: the window never closes silently — every path routes to `:PAUSE_MENU` which pauses before redrawing the menu, and missing-Python is reported instead of crashing. The `chcp` line from V1 (a common flash-and-close culprit) is removed.

- [ ] **Step 2: Manual test**

Double-click `scraper\Launch.bat` in Explorer. Expected: the menu appears and stays open. Press `6` (Validate) to confirm it runs and pauses. Press `0` to exit.

---

## Task 13: Full Test Suite + Integration Run (user-driven)

- [ ] **Step 1: Run the entire unit test suite**

```powershell
scraper\venv\Scripts\python.exe -m pytest tests/ -v
```
Expected: all tests across discovery, parser, json/md/index writers, and config round-trip pass.

- [ ] **Step 2: Dry-run validation**

```powershell
scraper\venv\Scripts\python.exe scraper\run.py --validate
```
Expected: `tradedesk 117`, `web4 18`, `saleshub 21`, `Validation PASSED`.

- [ ] **Step 3: Smoke scrape one product (SalesHub — smallest at 21)**

Launch.bat → option `4`. Watch Chrome open and scrape. Then verify:
```powershell
Get-ChildItem "library\saleshub\versions" | Select-Object Name
Get-ChildItem "library\saleshub\versions\screenshots" | Select-Object Name
```
Expected: 21 `.json` + 21 `.md` files, and 21 `.png` screenshots.

- [ ] **Step 4: Spot-check a JSON file for full fidelity**

```powershell
scraper\venv\Scripts\python.exe -c "import json; from pathlib import Path; d=json.loads(Path('library/saleshub/versions/2.0.2.1.json').read_text(encoding='utf-8')); print('sections:', [k for k in d if k not in ('product','version','title','url','scraped_at','screenshot')]); print('enh rows:', len(d.get('enhancements', []))); print('first enh keys:', list(d['enhancements'][0].keys()))"
```
Expected: sections include `enhancements`, `bugs`, `schema_changes`; `enh rows: 8`; first-row keys include `sno`, `id`, `details`, `key_feature`, `behavior_change`, `risk`, `on_by_default`.

- [ ] **Step 5: Full run (all products) + indexes**

Launch.bat → option `1`. Then:
```powershell
Get-Content "scraper\state\last_run_report.json"
Get-ChildItem library -Recurse -Filter "*.md" | Select-Object FullName
```
Expected: report shows per-product `new/skipped/failed`; `INDEX.md` plus `CHANGELOG.md` / `features-list.md` / `bugs-list.md` exist for each product.

- [ ] **Step 6: Re-run to confirm incrementality**

Launch.bat → option `1` again. Expected: report shows `new=0`, `skipped` equal to the version counts (nothing re-scraped).

---

## Quick Reference

| Goal | Action |
|------|--------|
| One-time setup | Launch.bat → `9` |
| Health check (no scrape) | Launch.bat → `6` (or `run.py --validate`) |
| Refresh config URLs | Launch.bat → `7` (or `run.py --discover`) |
| Normal scrape (all) | Launch.bat → `1` |
| Scrape one product | Launch.bat → `2`/`3`/`4` |
| Force full re-scrape | Launch.bat → `5` |
| Rebuild indexes only | Launch.bat → `8` |
| Capture test fixtures | `python tests\capture_fixtures.py` |
| Run tests | `scraper\venv\Scripts\python.exe -m pytest tests/ -v` |
