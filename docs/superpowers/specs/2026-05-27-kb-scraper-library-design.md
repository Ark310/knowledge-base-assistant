# Design: Contoso KB Scraper & Release Notes Library
**Date:** 2026-05-27  
**Products:** TradeDesk, Web4, SalesHub  
**Site:** https://help.contoso.example (Atlassian Confluence, machine-whitelisted, no login required)

---

## Goal

Scrape the Contoso Knowledge Base at `help.contoso.example` to extract all Release Notes (versions, enhancements, bugs, schema changes) for three products — TradeDesk, Web4, and SalesHub — and build a structured, queryable local library of JSON + Markdown files with per-page screenshots. The library will serve as the foundation for future tasks: feature lists on demand, AI-assisted queries, changelog generation, and more.

---

## Folder Structure

```
Knowledge Base/
├── scraper/
│   ├── Launch.bat                        ← Double-click entry point (interactive menu)
│   ├── run.py                            ← CLI runner called by Launch.bat
│   ├── core.py                           ← Playwright browser, screenshots, state tracking
│   ├── config.py                         ← Product configs (names, base URLs, section heading aliases)
│   ├── state/
│   │   └── scraped_versions.json         ← Incremental run tracker
│   ├── parsers/
│   │   └── universal.py                  ← Single parser for all products and layouts
│   └── writers/
│       ├── json_writer.py                ← Saves per-version .json files
│       ├── md_writer.py                  ← Saves per-version .md files
│       └── index_generator.py            ← Builds CHANGELOG, features-list, bugs-list, master INDEX
│
├── library/
│   ├── tradedesk/
│   │   ├── versions/
│   │   │   ├── 3.0.19.json
│   │   │   ├── 3.0.19.md
│   │   │   └── screenshots/
│   │   │       └── 3.0.19.png
│   │   ├── CHANGELOG.md                  ← All versions newest-first
│   │   ├── features-list.md              ← All enhancements across all versions
│   │   └── bugs-list.md                  ← All bugs across all versions
│   ├── web4/
│   │   └── (same structure)
│   ├── saleshub/
│   │   └── (same structure)
│   └── INDEX.md                          ← Master index linking all products + versions
│
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-05-27-kb-scraper-library-design.md   ← This file
```

---

## Data Schema

### TradeDesk, Web4, SalesHub (unified — only present fields included)

```json
{
  "product": "tradedesk",
  "version": "3.0.19",
  "url": "https://help.contoso.example/display/TD/Version+3.0.19",
  "scraped_at": "2026-05-27T10:00:00",
  "enhancements": [
    { "id": "TFS-12345", "title": "Short title", "description": "Full detail text" }
  ],
  "bugs": [
    { "id": "TFS-67890", "title": "Short title", "description": "Full detail text" }
  ],
  "schema_changes": [
    { "description": "Added column X to table Y" }
  ],
  "tasks": [
    {
      "sno": 1,
      "tfs_id": "55103",
      "details": "Enhanced Post-Deal Navigation",
      "config_changes": "NO",
      "key_feature": "NO",
      "behavior_change": "NO",
      "risk": "LOW"
    }
  ],
  "screenshot": "library/tradedesk/versions/screenshots/3.0.19.png"
}
```

**Rules:**
- Fields present in the page → included in output
- Fields absent from the page → omitted entirely (no empty arrays)
- `tasks` is populated when the page contains a structured table; `enhancements`/`bugs`/`schema_changes` are populated when the page contains headed sections
- A page may have both (e.g. table + a bugs section) — both are captured

---

## Scraper Flow

### Step 1 — Discovery
Each product has a `release_notes_url` in `config.py`, auto-populated by running `traverse.py`. The scraper navigates there, finds all version links, and compares against `scraped_versions.json`. Already-scraped versions are skipped unless `--force` is passed.

**Confirmed product release notes index URLs:**
- TradeDesk: `https://help.contoso.example/display/TD` (or whichever candidate resolves first)
- Web4: `https://help.contoso.example/display/ReleaseNotesWeb4` (confirmed working URL)
- SalesHub: `https://help.contoso.example/display/SH` (or whichever candidate resolves first)

### Step 2 — Per-Page Scraping (visible Chrome)
For each new version URL, Playwright opens a real Chrome window. It:
1. Waits for the Confluence page to fully load (waits for the main content container)
2. Takes a full-page screenshot → saves to `library/<product>/versions/screenshots/<version>.png`
3. Extracts the page HTML and passes it to `universal.py`

### Step 3 — Universal Parsing
`universal.py` applies the following logic to every page regardless of product:

1. **Table detection:** If a `<table>` element is present in the main content area, extract it row by row into `tasks[]`
2. **Section detection:** Scan all headings (h1–h4) for known keywords:
   - *Enhancements*, *New Features*, *Enhancement* → `enhancements[]`
   - *Bugs*, *Bug Fixes*, *Bug* → `bugs[]`
   - *Schema Changes*, *Schema*, *Database Changes* → `schema_changes[]`
3. For each matched section heading, extract the following sibling content (lists, paragraphs) until the next heading
4. For each item, attempt to extract a TFS/Portal ID (pattern: numeric string or `TFS-XXXXX`) and separate it from the description text
5. Whatever is not found is simply not written to the output object

### Step 4 — Writing
- `json_writer.py` → `library/<product>/versions/<version>.json`
- `md_writer.py` → `library/<product>/versions/<version>.md` (human-readable rendering of the same data)

### Step 5 — State Update
The version string and URL are appended to `scraped_versions.json` with a timestamp.

### Step 6 — Index Generation
After all products finish, `index_generator.py` reads all version JSON files and rebuilds:
- `library/<product>/CHANGELOG.md` — all versions newest-first with summary counts
- `library/<product>/features-list.md` — all enhancements across all versions, grouped by version
- `library/<product>/bugs-list.md` — all bugs across all versions, grouped by version
- `library/INDEX.md` — master index with links to all three products and version counts

---

## Launcher — `scraper/Launch.bat`

Double-click `Launch.bat` from Windows Explorer to open an interactive terminal menu:

```
╔══════════════════════════════════════════╗
║   Contoso KB Scraper — Launch Menu      ║
╠══════════════════════════════════════════╣
║  1. Scrape ALL products (incremental)    ║
║  2. Scrape TradeDesk only                 ║
║  3. Scrape Web4 only                     ║
║  4. Scrape SalesHub only                  ║
║  5. Force re-scrape ALL (full refresh)   ║
║  6. Rebuild index files only             ║
║  7. Exit                                 ║
╚══════════════════════════════════════════╝
Enter choice [1-7]:
```

`Launch.bat` activates the Python virtual environment (if present) and calls `run.py` with the appropriate `--product` and `--force` flags based on the user's menu selection.

---

## Configuration — `config.py`

Holds per-product settings so the universal parser knows what to look for:

```python
PRODUCTS = {
    "tradedesk": {
        "display_name": "TradeDesk",
        "release_notes_url": "...",   # confirmed during site traversal phase
        "section_aliases": {
            "enhancements": ["enhancements and new features", "enhancements", "new features"],
            "bugs": ["bugs", "bug fixes"],
            "schema_changes": ["schema changes", "database changes"]
        }
    },
    "web4": { ... },
    "saleshub": { ... }
}
```

---

## Implementation Phases

### Phase 1 — Site Traversal & URL Mapping
Run `python scraper/traverse.py` — Playwright opens headed Chrome, tries known candidate URLs for each product (in priority order), collects ALL version links using three strategies, **auto-updates `config.py`** with the discovered `release_notes_url` values, and saves `scraper/state/url_map.json` for reference.

**Three discovery strategies (applied in order, deduplicated):**
1. **Confluence REST API** — `GET /rest/api/content?spaceKey=X&type=page` with pagination (most complete)
2. **Sidebar selectors** — 7 Confluence-specific CSS selectors for the AJAX-loaded page tree
3. **Content scan** — all `<a>` tags in page HTML

**Scroll + expand** is triggered before collection to load AJAX content. After the script completes, `config.py` is already updated — no manual step needed. Proceed directly to `Launch.bat`.

### Phase 2 — Core Scraper + Universal Parser
Build `core.py`, `universal.py`, and the writers. Test against 2–3 known version pages per product.

### Phase 3 — Launcher + Incremental State
Build `Launch.bat`, `run.py` CLI, and `scraped_versions.json` tracking.

### Phase 4 — Full Scrape Run
Run against all products, verify output library quality, fix any parser edge cases.

### Phase 5 — Index Generation
Build and run `index_generator.py` to produce all summary and index files.

---

## Dependencies

- Python 3.10+
- `playwright` (`pip install playwright` + `playwright install chromium`)
- `beautifulsoup4` (`pip install beautifulsoup4`)
- `lxml` (`pip install lxml`)
- No database, no external API calls, no authentication

---

## Non-Goals

- No login/session handling (site is whitelisted)
- No scraping of non-Release Notes content (system admin docs, training videos, etc.)
- No automated scheduling (manual run via launcher)
- No web UI for the library (plain files only, for now)
