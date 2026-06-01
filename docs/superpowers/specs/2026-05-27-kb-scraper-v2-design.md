# Design: Contoso KB Scraper & Release Notes Library — V2
**Date:** 2026-05-27
**Products:** TradeDesk, Web4, SalesHub
**Site:** https://help.contoso.example (Atlassian Confluence, machine-whitelisted for public spaces, no login)
**Supersedes:** `2026-05-27-kb-scraper-library-design.md` (V1)

---

## Why V2

V1 was built against fabricated assumptions and failed on the live site. Live traversal on 2026-05-27 established ground truth and root-caused four failures:

1. **SalesHub discovery errored.** V1 guessed candidate URLs (`category/sh`, `display/SH`, `display/SalesHub`). `category/sh` is permission-locked (redirects to login with `permissionViolation=true`), `display/SH` is 404. The real space is `SHReleaseNotes`, and its pages are titled `SalesHub WEB Version X.X.X.X` — not `Version X`, so even a "title starts with Version" filter would miss them.
2. **Junk links polluted output.** The REST API returned clean data, but V1 also ran sidebar + content anchor scans and merged them, and its filter only required "contains a digit". Result: `Attachments (0)`, `Resolved comments (0)`, date-diff links, and author links (`~contoso2`) leaked into the version list.
3. **Config transfer silently failed.** V1 string-patched `config.py` source in place. It did not persist — all three `release_notes_url` values remained empty after a run.
4. **The parser cannot read real pages.** V1 expected bullet lists (`<ul><li>12345 - text</li>`) plus one global table. Real pages place a **structured table under every section heading**, with product-specific column schemas. V1 would mis-parse every live page.

### Ground truth (verified live, 2026-05-27)

| Product | Space key | Index URL | Version pages (REST API) |
|---|---|---|---|
| TradeDesk | `releasenotes` | `https://help.contoso.example/display/releasenotes` | 117 |
| Web4 | `ReleaseNotesWeb4` | `https://help.contoso.example/display/ReleaseNotesWeb4` | 18 |
| SalesHub | `SHReleaseNotes` | `https://help.contoso.example/display/SHReleaseNotes` | 21 |

The Confluence REST API (`/rest/api/content?spaceKey=<key>&type=page`) returned clean, complete, paginated results for all three with zero junk. This is the V2 discovery engine.

Observed real page structure (sample pages, one per product):
- Each page has section headings: `Enhancements and New Features`, `Bugs`, `Schema Changes` (TradeDesk, SalesHub) or `Tasks`, `Schema Changes` (Web4). May also contain a `Table of Contents` macro (ignore).
- **Each section heading is followed by a table.** Columns vary per product:
  - TradeDesk: `Sr. #`, `Task ID`, `Module`, `New Feature/ Improvement of Current Feature`, `Prerequisites`, `Details`, `Key Feature`, `Is there a change to previous behaviour?`, `Risk assessment: High:… Medium:… Low:…`, `Is this Feature 'ON' by default?`
  - Web4: `S.No`, `TFS/Portal ID`, `Details`, `Configuration Changes`, `Key Feature`, `Is there a change to previous behavior?`, `Risk assessment: …`, `Is this Feature 'ON' by default?`
  - SalesHub: `S.No`, `Portal/TFS ID`, `Details`, `Configuration Changes`, `Key Features`, `Is there a change to previous behavior?`, `Risk assessment`, `Is this Feature 'ON' by default?`

---

## Goal

Scrape the Contoso KB Release Notes for TradeDesk, Web4, and SalesHub into a structured, queryable local library (JSON + Markdown + per-page screenshots), with production-grade robustness: deterministic discovery, full-fidelity parsing, resilient runtime, structured logging, run reports, and a dry-run validation mode. The library is the foundation for later tasks (feature lists, AI queries, changelog generation).

---

## Folder Structure

```
Knowledge Base/
├── scraper/
│   ├── Launch.bat                 ← robust interactive menu (never closes silently)
│   ├── run.py                     ← orchestrator (modes, logging, retries, run report)
│   ├── discovery.py               ← NEW: REST API version-page discovery
│   ├── core.py                    ← Browser wrapper + StateTracker
│   ├── config.py                  ← space keys (pre-seeded), section aliases, column map, paths
│   ├── requirements.txt
│   ├── state/
│   │   ├── scraped_versions.json  ← incremental run tracker
│   │   ├── run.log                ← structured run log
│   │   └── last_run_report.json   ← machine-readable summary of the last run
│   ├── parsers/
│   │   └── universal.py           ← REWRITTEN: section→table extraction, full-fidelity columns
│   └── writers/
│       ├── json_writer.py
│       ├── md_writer.py
│       └── index_generator.py
├── library/
│   ├── tradedesk/
│   │   ├── versions/
│   │   │   ├── 3.0.1.9.json
│   │   │   ├── 3.0.1.9.md
│   │   │   └── screenshots/3.0.1.9.png
│   │   ├── CHANGELOG.md
│   │   ├── features-list.md
│   │   └── bugs-list.md
│   ├── web4/   (same structure)
│   ├── saleshub/ (same structure)
│   └── INDEX.md
├── tests/
│   ├── fixtures/
│   │   ├── tradedesk_real.html      ← real captured page
│   │   ├── web4_real.html          ← real captured page
│   │   ├── saleshub_real.html       ← real captured page
│   │   ├── tradedesk_rest.json      ← real captured REST API response
│   │   ├── web4_rest.json
│   │   └── saleshub_rest.json
│   ├── test_discovery.py
│   ├── test_universal_parser.py
│   ├── test_json_writer.py
│   ├── test_md_writer.py
│   ├── test_index_generator.py
│   └── test_config_roundtrip.py
└── docs/superpowers/specs/2026-05-27-kb-scraper-v2-design.md  ← this file
```

---

## Component Designs

### config.py

Holds static, pre-seeded, known-good values so the scraper works out of the box (fixes the V1 "config wasn't smooth" pain). No manual editing required.

```python
PRODUCTS = {
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
    "web4":   { ... "space_key": "ReleaseNotesWeb4",  "release_notes_url": "https://help.contoso.example/display/ReleaseNotesWeb4", ... },
    "saleshub":{ ... "space_key": "SHReleaseNotes",   "release_notes_url": "https://help.contoso.example/display/SHReleaseNotes",  ... },
}

# Canonical column normalization (lowercased header → canonical snake_case key)
COLUMN_SYNONYMS = {
    "sr. #": "sno", "sr #": "sno", "s.no": "sno", "sno": "sno", "#": "sno", "no": "sno",
    "task id": "id", "tfs/portal id": "id", "portal/tfs id": "id", "tfs id": "id", "portal id": "id", "id": "id",
    "module": "module",
    "details": "details", "description": "details",
    "new feature/ improvement of current feature": "feature_type",
    "prerequisites": "prerequisites",
    "configuration changes": "config_changes",
    "key feature": "key_feature", "key features": "key_feature",
    "is there a change to previous behavior?": "behavior_change",
    "is there a change to previous behaviour?": "behavior_change",
    # Risk header is a long blob beginning with "risk assessment" — matched by prefix in code
    "is this feature 'on' by default?": "on_by_default",
}
```

Note: the Risk column header is a long multi-line blob (`Risk assessment: High:… Medium:… Low:…`). Normalization matches it by the `risk assessment` prefix, mapping to `risk`. Any header with no synonym is slugified (lowercase, non-alphanumerics → `_`) and kept — no column is dropped.

### discovery.py (NEW)

Single responsibility: given a space key, return a clean, complete list of version pages. No browser, no parsing.

```python
def discover_versions(space_key: str, http_get) -> list[dict]:
    """
    Returns [{"version": "2.0.2.1", "title": "SalesHub WEB Version 2.0.2.1",
              "url": "https://.../display/<key>/...", "page_id": "12345"}, ...]
    Paginates /rest/api/content?spaceKey=<key>&type=page until exhausted.
    Keeps only pages whose title contains a dotted version number.
    """
```

- `http_get` is injected (a callable that performs an HTTP GET and returns parsed JSON) so tests can pass saved fixture JSON with no network. The default implementation uses stdlib `urllib.request` — the site whitelist is IP-based (an isolated browser session reached both pages and the REST API without login), so discovery needs no browser at all.
- Pagination: `limit=100`, loop incrementing `start` by returned `size` until `start >= totalSize`.
- Version filter regex: `\d+\.\d+(?:\.\d+)+` (two or more dots → real version, not "Web 4.0"). The matched substring is the canonical `version`.
- URL built from each result's `_links.webui`, prefixed with the base URL.

A `validate_space_keys(products, http_get)` helper backs `--validate`: returns per-product `{ok: bool, count: int, error: str|None}`.

### core.py

- `Browser`: headed Chrome via Playwright (`channel="chrome"`). Methods: `open/close`, context-manager support, `navigate(url)` **with retry (3× exponential backoff) and configurable timeout**, `expand_confluence_macros()`, `screenshot(path)`, `get_content()`, `current_url()`. The browser is used only for rendering version pages and capturing screenshots — not for discovery (discovery uses stdlib HTTP).
- `StateTracker`: unchanged from V1 — `is_scraped`, `mark_scraped` (persists immediately), `get_scraped_versions`.

### parsers/universal.py (REWRITTEN)

```python
def parse_page(html, product, version, title, url, screenshot_path, section_aliases, column_synonyms) -> dict:
    """Returns metadata + one list per present section; absent sections omitted."""
```

Algorithm:
1. Locate the content area (`#main-content` → `.wiki-content` → `#content` → `body`).
2. For each heading (`h1–h4`), lowercase its text and match against `section_aliases` to resolve a canonical section name (`enhancements`/`bugs`/`schema_changes`/`tasks`). Ignore `Table of Contents`.
3. For a matched heading, find the **next sibling table** (skipping whitespace/text nodes). Parse it:
   - Header row = first `<tr>`; map each header via `column_synonyms` (prefix rule for `risk assessment`); unmapped → slugified key.
   - Each subsequent `<tr>` → a row dict keyed by the normalized headers (cell text, whitespace-collapsed). Skip fully empty rows.
4. Attach each section's row list to the result under its canonical name. Omit sections with no rows.
5. Metadata always present: `product`, `version`, `title`, `url`, `scraped_at`, `screenshot`.

`_extract_version(title)` returns the dotted version substring (shared with discovery's regex).

### writers/

- **json_writer.py:** `save_version(data, library_base) -> Path`, writes `<lib>/<product>/versions/<safe_version>.json`. `_safe_name` replaces spaces→`_`, `/`→`-`.
- **md_writer.py:** `save_version` + `_render_md`. Each present section renders as a Markdown table whose columns follow that section's own normalized keys (preserving full fidelity); column order taken from the first row's keys. Header block: product, version, title, URL, scraped time, screenshot path.
- **index_generator.py:** `generate_all(library_base, products)` rebuilds per-product `CHANGELOG.md` (newest-first, with per-version item counts), `features-list.md` (all `enhancements`/`tasks` rows grouped by version), `bugs-list.md` (all `bugs` rows grouped by version), and master `INDEX.md`. `_safe` matches json_writer (`/`→`-`, spaces→`_`). Handles products with zero versions without raising.

### run.py — orchestrator

Responsibilities: parse args, configure logging, run discovery, drive the browser, parse/write, track state, emit the run report.

Modes:
- `--all` — scrape all three products (incremental), then rebuild indexes.
- `--product <key>` — scrape one product, then rebuild indexes.
- `--force` — ignore state, re-scrape everything in scope.
- `--index-only` — rebuild index files from existing JSON; no browser.
- `--validate` — dry-run: check all space keys resolve via REST API, print version counts, write nothing, no browser.
- `--discover` — re-derive index URLs/space keys via REST API and **robustly rewrite config.py**, verifying the write by re-importing config (guards against the V1 silent failure). Because keys are pre-seeded, this is a refresh/repair tool, not a required step.

Per-version loop: skip if already scraped (unless `--force`) → navigate (with retry) → expand macros → screenshot → `get_content` → `parse_page` → write JSON + MD → `mark_scraped`. Any per-page exception is logged and counted as a failure; the run continues.

Run report (printed and written to `state/last_run_report.json`): per product `{discovered, new, skipped, failed}` plus a list of failed URLs.

### Launch.bat — robust menu

Root cause of "flash-and-close": an error (venv/Python resolution under the OneDrive path) before the menu draws, with nothing pausing the window. V2:
- `cd /d "%~dp0.."` to the Knowledge Base root; all paths quoted.
- Detect `scraper\venv\Scripts\python.exe`. If missing, offer **option: one-time setup** (create venv, `pip install -r requirements.txt`, `playwright install chromium`) rather than failing.
- Invoke Python via the venv's `python.exe` explicitly (no PATH dependency).
- **Never close silently:** wrap actions so errors print and `pause`; return to menu after each action; only exit on the explicit Exit choice.
- Menu options: 1 Scrape ALL · 2 TradeDesk · 3 Web4 · 4 SalesHub · 5 Force ALL · 6 Validate (dry-run) · 7 Discover/refresh URLs · 8 Rebuild indexes · 9 One-time setup · 0 Exit.

---

## Data Schema (per version JSON)

```json
{
  "product": "saleshub",
  "version": "2.0.2.1",
  "title": "SalesHub WEB Version 2.0.2.1",
  "url": "https://help.contoso.example/display/SHReleaseNotes/SalesHub+WEB+Version+2.0.2.1",
  "scraped_at": "2026-05-27T10:00:00",
  "screenshot": "library/saleshub/versions/screenshots/2.0.2.1.png",
  "enhancements": [
    {"sno": "1", "id": "12345", "details": "…", "config_changes": "NO",
     "key_feature": "YES", "behavior_change": "NO", "risk": "LOW", "on_by_default": "YES"}
  ],
  "bugs": [ { "...": "..." } ],
  "schema_changes": [ { "...": "..." } ]
}
```

Rules: sections present on the page are included as row lists; absent sections omitted entirely. Every table column is preserved (canonical key when known, slugified header otherwise).

---

## Testing / QA

- **Real fixtures:** capture one representative real page per product (`*_real.html`) and one real REST response per product (`*_rest.json`) into `tests/fixtures/`. All parser/discovery tests run against these — no network.
- **test_discovery.py:** version filter keeps real versions and rejects junk (attachments, comments, How-to articles, author/diff links); pagination loop terminates; URLs built correctly.
- **test_universal_parser.py:** for each product's real fixture — correct sections detected, correct row counts, all columns captured, risk-blob header normalized to `risk`, unknown columns slugified and retained, TOC ignored.
- **test_json_writer.py / test_md_writer.py:** file paths, content round-trip, section-table rendering, absent sections omitted, version-string sanitization.
- **test_index_generator.py:** changelog/features/bugs/master index generation; empty-product safety.
- **test_config_roundtrip.py:** `--discover` write path produces a config that re-imports with the expected values (regression guard for the V1 silent failure).
- **Manual integration:** documented Launch.bat pass (validate → scrape one product → scrape all → rebuild indexes), verifying real output files and screenshots.

---

## Implementation Phases

1. **Config + discovery** — pre-seed `config.py` with space keys/column map; build `discovery.py`; capture real REST fixtures; tests.
2. **Parser rewrite** — capture real HTML fixtures; rewrite `universal.py` for section→table extraction with full-fidelity columns; tests.
3. **Writers** — adapt json/md/index writers to the new section-table schema; tests.
4. **Core + orchestrator** — `core.py` retries/timeouts + REST helper; `run.py` modes, logging, retries, run report.
5. **Launcher** — robust `Launch.bat` with one-time setup and validate/discover options.
6. **Integration run** — full live run, verify library quality, fix parser edge cases against real pages.

---

## Dependencies

- Python 3.10+
- `playwright` (+ `playwright install chromium`; uses installed Chrome via `channel="chrome"`)
- `beautifulsoup4`, `lxml`
- `pytest`
- No database, no auth (public spaces are whitelisted; SalesHub's `category/sh` is permission-locked but its release-notes space `SHReleaseNotes` is publicly readable).

---

## Non-Goals

- No login/session handling.
- No scraping of non-Release-Notes content (How-to articles, admin docs, training).
- No automated scheduling (manual run via launcher).
- No web UI for the library (plain files for now).
- No scraping of the permission-locked `category/sh` dashboard (not needed — REST API on `SHReleaseNotes` covers SalesHub).
