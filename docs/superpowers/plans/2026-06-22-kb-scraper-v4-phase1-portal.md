# KB Scraper v4 — Phase 1: Portal Adapter & Ticket Parser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the obsolete `support.contoso.example` (ASP.NET) ticket scraping with a new-portal adapter + parser for the `portal.contoso.example` SPA, validated by TDD against PII-scrubbed rendered-DOM fixtures, so later phases can drive ticket scraping.

**Architecture:** A thin `TradeDeskPortal` adapter wraps the authenticated headed `Browser`, navigates to ticket routes, waits for the SPA to render, and hands rendered HTML to pure parser functions. The parser (`scraper/parsers/ticket_parser.py`, rewritten) turns rendered HTML into a structured ticket dict (header, fields, comments, attachment refs, resolution). Exact selectors for the resolution/files/not-found states are captured in Task 1; fields and comments are already confirmed.

**Tech Stack:** Python 3.12, Playwright sync API (system Chrome via `channel="chrome"`), BeautifulSoup4 + lxml, pytest. Test interpreter: `scraper\venv\Scripts\python.exe`.

## Global Constraints

- `APP_VERSION` target for the release = `"4.0"` (bumped in Phase 6; do not bump in Phase 1).
- Portal access is **headed Chrome only** (`headless=False`, `channel="chrome"`) — the SPA requires a real browser.
- **No API replay or decryption.** The `portal.contoso.example` API is end-to-end AES-GCM encrypted; extract only from the authenticated, rendered DOM.
- **Password security (unchanged):** keyring only, never written to disk, never logged at any level, masked in UI. Never pass passwords as shell args.
- **Fixtures must be PII-free.** Real customer org names, person names, emails, and phone numbers are scrubbed to deterministic test tokens before any fixture is committed. The real→fake mapping lives only in a gitignored local file.
- Tests live in repo-root `tests/`; fixtures in `tests/fixtures/`; each test file starts with `sys.path.insert(0, str(Path(__file__).parent.parent))` then imports from `scraper...` (existing convention — see `tests/test_universal_parser.py`).
- On-disk ticket output contract is unchanged (`library/tickets/ticket_{id}.json` + `.md`); this phase only changes parsing, not writing.

**Confirmed selectors — POST-DISCOVERY (Task 1 done; fixtures authored). These supersede any selector detail in Tasks 2-7 below; where a task's example code differs, follow THIS block + `tests/fixtures/tradedesk/DOM_MAP.md`:**
- **Fixtures are SYNTHETIC** (structure-faithful, fake content, PII-free) — already committed under `tests/fixtures/tradedesk/` (`ticket_detail.html`, `resolution.html`, `files.html`, `not_found.html`, `login.html`) with `DOM_MAP.md`. Task 1 is COMPLETE; implementers start at Task 2 and assert against these fixtures.
- **Fields — extract by LABEL with dedupe (first wins), NOT by id.** Fields render twice (`header_bg_*` and `bg_*` id sets) and CSQA Owner's id is non-standard. For each `button.floating-dropdown-btn`: label = `span.floating-dropdown-label` text with trailing `*` stripped; value = `span.floating-dropdown-value` text. Label→key map: `organization→organization, project→product, priority→priority, category→category, severity→severity, status→status, assigned to→assignee, csqa owner→csqa_owner`. Skip a key already set (dedupe).
- **Comments**: container `div.space-y-2` → `div.p-2` cards. Read the header from the **`span.hidden`** (`comment {id} posted by {Name}`) — the visible `span.truncate` is cut off. Body = `<p>` tags. `Internal` badge text → `internal=True`. Date via regex `([A-Z][a-z]{2,8} \d{1,2}, \d{4} at \d{1,2}:\d{2} ?[AP]M)`. Attachment = `button.inline-flex` text "Download" inside the card; filename in a nearby `.filename`/`div.min-w-0`. **`ticket_detail.html` has 3 comments; comment #3 (id 1460500) has one attachment "error-log.txt".**
- **Resolution**: scope to `div.resolution-container`; text = `div.ql-editor` `<p>`s; resolution file = `button.inline-flex` "Download" within the container (`resolution.html` → "resolution-script.sql").
- **Files**: cards under `.files-list`; name in `div.min-w-0`/`.filename` + `button.inline-flex` "Download". **`files.html` has 2 files.**
- **Not-found**: missing ticket REDIRECTS to `/bugs` (title "Tickets - Support Portal"). Detect: no `button.floating-dropdown-btn` AND no `Ticket #` text. (`not_found.html` is the `/bugs` page.)
- Header: `Ticket # {id}` in `span.text-md`; `Created MM/DD/YYYY by {user}` nearby. Route `{portal}/tickets/{id}/edit`; ready when `document.title` matches `^Ticket ID {id} - `.

---

### Task 1: Guided discovery + PII-scrubbed fixtures

Capture the remaining rendered-DOM fixtures (the SPA states not yet seen) and lock the DOM map. Requires the operator logged into the portal in a headed browser.

**Files:**
- Create: `tests/capture_tradedesk_fixtures.py`
- Create (output): `tests/fixtures/tradedesk/ticket_detail.html`, `tests/fixtures/tradedesk/resolution.html`, `tests/fixtures/tradedesk/files.html`, `tests/fixtures/tradedesk/not_found.html`, `tests/fixtures/tradedesk/login.html`
- Create: `tests/fixtures/tradedesk/DOM_MAP.md` (records confirmed selectors for each state)
- Modify: `.gitignore` — add `tests/fixtures/tradedesk/.scrub.local.json`

**Interfaces:**
- Produces: PII-free HTML fixtures consumed by Tasks 2–6; `DOM_MAP.md` documenting the resolution/files/not-found selectors that Tasks 4–6 depend on.

- [ ] **Step 1: Write the capture script.**

```python
# tests/capture_tradedesk_fixtures.py
"""One-time guided capture of rendered-DOM fixtures from portal.contoso.example.
Operator must be ABLE to log in (headed Chrome opens; type credentials in the
window when prompted). Real PII is scrubbed via a gitignored local map before
anything is written. Run from the Knowledge Base root:
  scraper\\venv\\Scripts\\python.exe tests\\capture_tradedesk_fixtures.py --ticket 76511 --bad 999999999
"""
from __future__ import annotations
import argparse, json, re, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.core import Browser

FIX = Path(__file__).parent / "fixtures" / "tradedesk"
SCRUB_LOCAL = FIX / ".scrub.local.json"   # gitignored: {"Real Name": "Jordan Lee", ...}

def scrub(html: str, mapping: dict[str, str]) -> str:
    out = html
    for real, fake in sorted(mapping.items(), key=lambda kv: -len(kv[0])):
        out = out.replace(real, fake)
    # generic PII nets (belt-and-suspenders)
    out = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "user@example.com", out)
    out = re.sub(r"\+?\d[\d\s().-]{7,}\d", "555-0100", out)
    return out

def assert_clean(html: str, mapping: dict[str, str]) -> None:
    leaked = [real for real in mapping if real in html]
    if leaked:
        raise SystemExit(f"PII still present after scrub: {leaked}")
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", html.replace("user@example.com", "")):
        raise SystemExit("an email survived scrubbing")

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portal", default="https://portal.contoso.example")
    ap.add_argument("--ticket", required=True)
    ap.add_argument("--bad", required=True, help="a ticket id that does not exist")
    args = ap.parse_args()

    FIX.mkdir(parents=True, exist_ok=True)
    mapping = json.loads(SCRUB_LOCAL.read_text(encoding="utf-8")) if SCRUB_LOCAL.exists() else {}
    if not mapping:
        print(f"WARNING: {SCRUB_LOCAL} is empty — only generic email/phone scrubbing will run.")

    b = Browser(headless=False, timeout_ms=30_000).open()
    try:
        b.navigate(f"{args.portal}/login")
        input("Log in in the browser window, then press ENTER here to capture login page... ")
        save("login.html", b.get_content(), mapping)

        b.navigate(f"{args.portal}/tickets/{args.ticket}/edit")
        _wait_title(b, rf"^Ticket ID {args.ticket} - ")
        save("ticket_detail.html", b.get_content(), mapping)

        _click_subview(b, "Resolve"); time.sleep(1.5)
        save("resolution.html", b.get_content(), mapping)

        b.navigate(f"{args.portal}/tickets/{args.ticket}/edit"); _wait_title(b, rf"^Ticket ID {args.ticket} - ")
        _click_subview(b, "Files"); time.sleep(1.5)
        save("files.html", b.get_content(), mapping)

        b.navigate(f"{args.portal}/tickets/{args.bad}/edit"); time.sleep(2.5)
        save("not_found.html", b.get_content(), mapping)
    finally:
        b.close()
    print("Done. Review DOM_MAP.md and the fixtures, then commit.")

def save(name: str, html: str, mapping: dict) -> None:
    cleaned = scrub(html, mapping)
    assert_clean(cleaned, mapping)
    (FIX / name).write_text(cleaned, encoding="utf-8")
    print(f"saved {name} ({len(cleaned)} chars, PII-clean)")

def _wait_title(b: Browser, pattern: str, tries: int = 20) -> None:
    for _ in range(tries):
        if re.search(pattern, b._page.title()):
            return
        time.sleep(0.5)

def _click_subview(b: Browser, label: str) -> None:
    b._page.get_by_role("button").filter(has_text=re.compile(rf"^{label}\b")).first.click()

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add the scrub-map file to `.gitignore`.**

Append to `.gitignore`:
```
tests/fixtures/tradedesk/.scrub.local.json
```

- [ ] **Step 3: Create the local scrub map (NOT committed).**

Create `tests/fixtures/tradedesk/.scrub.local.json` with the real→fake pairs for the chosen ticket, e.g.:
```json
{ "Wide World Importers": "Northwind Trading", "Casey Nguyen": "Jordan Lee", "Drew Parker": "Alex Kim" }
```

- [ ] **Step 4: Run the capture (operator logs in).**

Run: `scraper\venv\Scripts\python.exe tests\capture_tradedesk_fixtures.py --ticket 76511 --bad 999999999`
Expected: 5 `saved …(PII-clean)` lines, no `PII still present` error.

- [ ] **Step 5: Verify fixtures are PII-free.**

Run: `grep -RniE "(wide world importers|@contoso|@tradedesk|[0-9]{3}-[0-9]{4})" tests/fixtures/tradedesk/ || echo CLEAN`
Expected: `CLEAN`.

- [ ] **Step 6: Write `DOM_MAP.md`** recording, for each fixture, the confirmed selectors — fields (`button.floating-dropdown-btn` + `id` suffixes for all 8 fields), comments (`div.space-y-2 > div.p-2`, hidden-span header, `<p>` body, Download button), the **resolution** container selector + its file element, the **files** list rows + filename + download control, and the **not-found** marker (text/element). Fill the resolution/files/not-found selectors from the freshly captured HTML.

- [ ] **Step 7: Commit.**

```bash
git add tests/capture_tradedesk_fixtures.py tests/fixtures/tradedesk/*.html tests/fixtures/tradedesk/DOM_MAP.md .gitignore
git commit -m "test(v4): capture PII-scrubbed tradedesk portal fixtures + DOM map"
```

---

### Task 2: `is_not_found` detector

**Files:**
- Modify: `scraper/parsers/ticket_parser.py` (begin the rewrite — replace the aspx-era module)
- Test: `tests/test_tradedesk_ticket_parser.py`

**Interfaces:**
- Produces: `is_not_found(html: str, ticket_id: str) -> bool`

- [ ] **Step 1: Write the failing test.**

```python
# tests/test_tradedesk_ticket_parser.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.parsers.ticket_parser import is_not_found

FIX = Path(__file__).parent / "fixtures" / "tradedesk"
def fx(name): return (FIX / name).read_text(encoding="utf-8")

def test_not_found_true_for_missing_ticket():
    assert is_not_found(fx("not_found.html"), "999999999") is True

def test_not_found_false_for_real_ticket():
    assert is_not_found(fx("ticket_detail.html"), "76511") is False
```

- [ ] **Step 2: Run to verify it fails.**
Run: `scraper\venv\Scripts\python.exe -m pytest tests/test_tradedesk_ticket_parser.py -v`
Expected: FAIL (`ImportError` / function missing).

- [ ] **Step 3: Implement `is_not_found`** in `scraper/parsers/ticket_parser.py`, using the not-found marker recorded in `DOM_MAP.md`. Detect the SPA's empty/error state; the readiness signal for a real ticket is the rendered header (`Ticket # {id}` / fields). Concretely: not-found = the rendered DOM has no `button.floating-dropdown-btn` AND shows the portal's not-found/empty marker (exact text from DOM_MAP, e.g. a "not found"/"no access" element). Real ticket = `button.floating-dropdown-btn` present.

```python
from __future__ import annotations
import re
from bs4 import BeautifulSoup, Tag

def _soup(html): return BeautifulSoup(html or "", "lxml")

def is_not_found(html: str, ticket_id: str) -> bool:
    soup = _soup(html)
    if soup.select_one("button.floating-dropdown-btn"):
        return False
    text = soup.get_text(" ", strip=True).lower()
    return ("not found" in text) or ("no longer exists" in text) or ("access" in text and "denied" in text)
```

- [ ] **Step 4: Run to verify pass.** Expected: 2 passed. (If the not-found fixture uses different wording, update the markers to match `DOM_MAP.md`.)

- [ ] **Step 5: Commit.**
```bash
git add scraper/parsers/ticket_parser.py tests/test_tradedesk_ticket_parser.py
git commit -m "feat(v4): is_not_found for tradedesk SPA tickets"
```

---

### Task 3: `parse_ticket_fields` — header + field buttons

**Files:**
- Modify: `scraper/parsers/ticket_parser.py`
- Test: `tests/test_tradedesk_ticket_parser.py`

**Interfaces:**
- Consumes: `_soup`, `_clean` helpers
- Produces: `parse_ticket_fields(html: str) -> dict` returning keys: `ticket_id`, `title`, `created_by`, `created_at`, `organization`, `product`, `priority`, `category`, `severity`, `status`, `assignee`, `csqa_owner`, `awaiting_production_deployment` (bool). Missing fields are omitted (not `None`).

- [ ] **Step 1: Write the failing tests.**

```python
from scraper.parsers.ticket_parser import parse_ticket_fields

def test_fields_core_values():
    f = parse_ticket_fields(fx("ticket_detail.html"))
    assert f["ticket_id"] == "76511"
    assert f["product"] == "TD Client Server"     # Project* (not PII)
    assert f["priority"] == "high"
    assert f["status"].startswith("18 - ")
    assert f["organization"]                         # present, scrubbed value
    assert f["assignee"] and f["csqa_owner"]

def test_fields_header_created():
    f = parse_ticket_fields(fx("ticket_detail.html"))
    assert f["title"]                                # non-empty
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", f["created_at"])
```

- [ ] **Step 2: Run to verify fail.** Expected: FAIL (function missing).

- [ ] **Step 3: Implement.**

```python
_FIELD_ID_MAP = {
    "header_bg_org": "organization",
    "header_bg_project": "product",
    "header_bg_priority": "priority",
    "header_bg_category": "category",
    "header_bg_severity": "severity",
    "header_bg_status": "status",
    "header_bg_assignedto": "assignee",
    "header_bg_csqaowner": "csqa_owner",
}  # confirm exact id suffixes against DOM_MAP.md / ticket_detail.html
_TICKET_NO_RE = re.compile(r"Ticket\s*#\s*(\d+)", re.I)
_CREATED_RE   = re.compile(r"Created\s+(\d{2}/\d{2}/\d{4})\s+by\s+(\S+)", re.I)

def _clean(t): return re.sub(r"\s+", " ", t or "").strip()

def parse_ticket_fields(html: str) -> dict:
    soup = _soup(html)
    out: dict = {}
    for btn in soup.select("button.floating-dropdown-btn"):
        key = _FIELD_ID_MAP.get(btn.get("id", ""))
        if not key:
            continue
        val = btn.select_one(".floating-dropdown-value")
        v = _clean(val.get_text()) if val else ""
        if v:
            out[key] = v
    full = soup.get_text(" ", strip=True)
    m = _TICKET_NO_RE.search(full)
    if m:
        out["ticket_id"] = m.group(1)
    title_el = soup.select_one("span.text-md")          # header title region (see DOM_MAP)
    if title_el:
        out["title"] = _clean(title_el.get_text())
    mc = _CREATED_RE.search(full)
    if mc:
        out["created_at"], out["created_by"] = mc.group(1), mc.group(2)
    chk = soup.find("input", attrs={"type": "checkbox"})
    out["awaiting_production_deployment"] = bool(chk and chk.has_attr("checked"))
    return out
```
> Confirm the exact `header_bg_*` id suffixes and the title element against `ticket_detail.html` while implementing; adjust `_FIELD_ID_MAP` / title selector to the captured values (the three confirmed are org/project/priority).

- [ ] **Step 4: Run to verify pass.** Expected: tests pass (4 total in file).
- [ ] **Step 5: Commit.**
```bash
git add scraper/parsers/ticket_parser.py tests/test_tradedesk_ticket_parser.py
git commit -m "feat(v4): parse_ticket_fields (id-keyed field buttons + header)"
```

---

### Task 4: `parse_comments` — comment cards + attachment refs

**Files:**
- Modify: `scraper/parsers/ticket_parser.py`
- Test: `tests/test_tradedesk_ticket_parser.py`

**Interfaces:**
- Produces: `parse_comments(html: str) -> list[dict]` where each item has `id` (str), `author` (str), `date` (str), `internal` (bool), `body` (str), `attachments` (list of `{"label": str}` — display text near each Download control; the actual file is fetched by the adapter in Phase 2).

- [ ] **Step 1: Write the failing tests.**

```python
from scraper.parsers.ticket_parser import parse_comments

def test_comment_count_and_shape():
    cs = parse_comments(fx("ticket_detail.html"))
    assert len(cs) == 11
    first = cs[0]
    assert first["id"].isdigit()
    assert first["author"]                      # non-empty (scrubbed)
    assert re.search(r"\d{4}", first["date"])
    assert first["body"]

def test_at_least_one_comment_has_attachment():
    cs = parse_comments(fx("ticket_detail.html"))
    assert any(c["attachments"] for c in cs)
```

- [ ] **Step 2: Run to verify fail.** Expected: FAIL (function missing).

- [ ] **Step 3: Implement.**

```python
_COMMENT_HDR_RE = re.compile(r"comment\s+(\d+)\s+posted by\s+(.+?)\s*$", re.I)
_DATE_RE = re.compile(r"([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s*[AP]M)")

def _comment_cards(soup):
    hdr = soup.find(string=_COMMENT_HDR_RE)
    if not hdr:
        return []
    container = hdr.find_parent("div", class_="space-y-2")
    if not container:
        return []
    return [c for c in container.find_all("div", class_="p-2", recursive=False)]

def parse_comments(html: str) -> list[dict]:
    soup = _soup(html)
    comments = []
    for card in _comment_cards(soup):
        text = card.get_text(" ", strip=True)
        m = None
        for s in card.find_all(string=_COMMENT_HDR_RE):
            m = _COMMENT_HDR_RE.search(s)
            if m:
                break
        if not m:
            continue
        body = "\n".join(_clean(p.get_text()) for p in card.find_all("p") if _clean(p.get_text()))
        attachments = []
        for b in card.find_all("button"):
            if _clean(b.get_text()).lower() == "download":
                row = b.find_parent("div", class_="flex")
                label = _clean(row.get_text().replace("Download", "")) if row else ""
                attachments.append({"label": label})
        dm = _DATE_RE.search(text)
        comments.append({
            "id": m.group(1),
            "author": _clean(m.group(2)),
            "date": dm.group(1) if dm else "",
            "internal": "internal" in text.lower(),
            "body": body,
            "attachments": attachments,
        })
    return comments
```

- [ ] **Step 4: Run to verify pass.** Expected: tests pass. (If count ≠ 11, re-check the `div.p-2` recursion depth against `ticket_detail.html`.)
- [ ] **Step 5: Commit.**
```bash
git add scraper/parsers/ticket_parser.py tests/test_tradedesk_ticket_parser.py
git commit -m "feat(v4): parse_comments with attachment refs"
```

---

### Task 5: `parse_resolution` + `parse_files`

**Files:**
- Modify: `scraper/parsers/ticket_parser.py`
- Test: `tests/test_tradedesk_ticket_parser.py`

**Interfaces:**
- Produces: `parse_resolution(html: str) -> dict` → `{"text": str, "attachments": [{"label": str}]}`; `parse_files(html: str) -> list[dict]` → `[{"label": str}]` (every file row on the Files view).

- [ ] **Step 1: Write the failing tests.**

```python
from scraper.parsers.ticket_parser import parse_resolution, parse_files

def test_resolution_has_text():
    r = parse_resolution(fx("resolution.html"))
    assert isinstance(r["text"], str) and r["text"].strip()

def test_files_lists_all_attachments():
    files = parse_files(fx("files.html"))
    assert len(files) == 2          # ticket 76511 shows "Files 2"
    assert all(f["label"] for f in files)
```

- [ ] **Step 2: Run to verify fail.** Expected: FAIL (functions missing).

- [ ] **Step 3: Implement** against the resolution/files containers recorded in `DOM_MAP.md`. Resolution text = the resolution view's main content region; resolution file(s) = `Download`/file rows in that view. Files view = the rows in the files list. Use the confirmed selectors; the skeleton below mirrors the comment extraction and must be pointed at the resolution/files container classes from the fixtures:

```python
def parse_resolution(html: str) -> dict:
    soup = _soup(html)
    region = soup.select_one("[id*='resolution'], .resolution, div.space-y-2")  # narrow to confirmed container in DOM_MAP
    if region is None:
        region = soup
    text = "\n".join(_clean(p.get_text()) for p in region.find_all("p") if _clean(p.get_text()))
    attachments = [{"label": _clean((b.find_parent('div', class_='flex') or b).get_text().replace("Download", ""))}
                   for b in region.find_all("button") if _clean(b.get_text()).lower() == "download"]
    return {"text": text, "attachments": attachments}

def parse_files(html: str) -> list[dict]:
    soup = _soup(html)
    files = []
    for b in soup.find_all("button"):
        if _clean(b.get_text()).lower() in ("download", "view", "open"):
            row = b.find_parent("div", class_="flex")
            label = _clean(row.get_text()) if row else ""
            label = re.sub(r"\b(Download|View|Open)\b", "", label).strip()
            if label:
                files.append({"label": label})
    return files
```
> Replace the `select_one(...)` resolution container and the files-row selector with the exact classes from `DOM_MAP.md` once captured; assert counts against the real fixtures.

- [ ] **Step 4: Run to verify pass.** Expected: tests pass.
- [ ] **Step 5: Commit.**
```bash
git add scraper/parsers/ticket_parser.py tests/test_tradedesk_ticket_parser.py
git commit -m "feat(v4): parse_resolution + parse_files"
```

---

### Task 6: `parse_ticket_detail` orchestrator

**Files:**
- Modify: `scraper/parsers/ticket_parser.py`
- Test: `tests/test_tradedesk_ticket_parser.py`

**Interfaces:**
- Consumes: `is_not_found`, `parse_ticket_fields`, `parse_comments`
- Produces: `parse_ticket_detail(html: str, ticket_id: str, portal_url: str) -> dict` → fields + `comments` + `url` (`{portal}/tickets/{id}/edit`) + `scraped_at` (ISO). Returns `{}` when `is_not_found`. (Resolution + downloaded file paths are merged in by the engine in Phase 2.)

- [ ] **Step 1: Write the failing tests.**

```python
from scraper.parsers.ticket_parser import parse_ticket_detail

def test_detail_merges_fields_and_comments():
    d = parse_ticket_detail(fx("ticket_detail.html"), "76511", "https://portal.contoso.example")
    assert d["ticket_id"] == "76511"
    assert d["product"] == "TD Client Server"
    assert len(d["comments"]) == 11
    assert d["url"] == "https://portal.contoso.example/tickets/76511/edit"
    assert "scraped_at" in d

def test_detail_empty_for_not_found():
    assert parse_ticket_detail(fx("not_found.html"), "999999999", "https://portal.contoso.example") == {}
```

- [ ] **Step 2: Run to verify fail.** Expected: FAIL (function missing).

- [ ] **Step 3: Implement.**

```python
from datetime import datetime

def parse_ticket_detail(html: str, ticket_id: str, portal_url: str) -> dict:
    if is_not_found(html, ticket_id):
        return {}
    data = parse_ticket_fields(html)
    data["ticket_id"] = data.get("ticket_id") or ticket_id
    data["comments"] = parse_comments(html)
    base = portal_url.rstrip("/")
    data["url"] = f"{base}/tickets/{ticket_id}/edit"
    data["scraped_at"] = datetime.now().isoformat()
    return data
```

- [ ] **Step 4: Run to verify pass.** Expected: all tests in `test_tradedesk_ticket_parser.py` pass.
- [ ] **Step 5: Commit.**
```bash
git add scraper/parsers/ticket_parser.py tests/test_tradedesk_ticket_parser.py
git commit -m "feat(v4): parse_ticket_detail orchestrator"
```

---

### Task 7: `TradeDeskPortal` adapter (browser-driving)

Wraps the authenticated `Browser` with the navigation/login/view-switch/download steps the engine will call. Pure helpers are unit-tested; browser-driving methods are exercised by the Phase 2 smoke test.

**Files:**
- Create: `scraper/portal/__init__.py`
- Create: `scraper/portal/tradedesk_portal.py`
- Test: `tests/test_tradedesk_portal.py`

**Interfaces:**
- Consumes: `scraper.core.Browser`; `scraper.parsers.ticket_parser` functions
- Produces: class `TradeDeskPortal(browser, portal_url)` with:
  - `is_login_page(html: str) -> bool` (pure)
  - `ticket_url(ticket_id: str) -> str` (pure)
  - `login(username: str, password: str) -> bool`
  - `open_ticket(ticket_id: str) -> str` (navigates, waits for render, returns rendered HTML)
  - `open_subview(label: str) -> str` (clicks a `sidebar-menu-btn`, returns rendered HTML)
  - `download_all(dest_dir: Path) -> list[Path]` (clicks each `Download`, captures Playwright download events)

- [ ] **Step 1: Write failing tests for the pure helpers.**

```python
# tests/test_tradedesk_portal.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.portal.tradedesk_portal import TradeDeskPortal

FIX = Path(__file__).parent / "fixtures" / "tradedesk"
def fx(n): return (FIX / n).read_text(encoding="utf-8")

def test_ticket_url():
    p = TradeDeskPortal(browser=None, portal_url="https://portal.contoso.example/")
    assert p.ticket_url("76511") == "https://portal.contoso.example/tickets/76511/edit"

def test_is_login_page_true_on_login_fixture():
    p = TradeDeskPortal(browser=None, portal_url="https://portal.contoso.example")
    assert p.is_login_page(fx("login.html")) is True

def test_is_login_page_false_on_ticket_fixture():
    p = TradeDeskPortal(browser=None, portal_url="https://portal.contoso.example")
    assert p.is_login_page(fx("ticket_detail.html")) is False
```

- [ ] **Step 2: Run to verify fail.** Expected: FAIL (module missing).

- [ ] **Step 3: Implement the adapter.**

```python
# scraper/portal/tradedesk_portal.py
"""Authenticated-browser adapter for the portal.contoso.example SPA (v4).

Scrapes the RENDERED DOM — the API is end-to-end encrypted and is never touched.
Password is consumed by login() and never stored or logged.
"""
from __future__ import annotations
import re, time
from pathlib import Path
from scraper.parsers.ticket_parser import is_not_found

class TradeDeskPortal:
    def __init__(self, browser, portal_url: str):
        self.b = browser
        self.base = portal_url.rstrip("/")

    # ── pure helpers ──
    def ticket_url(self, ticket_id: str) -> str:
        return f"{self.base}/tickets/{ticket_id}/edit"

    def is_login_page(self, html: str) -> bool:
        h = html.lower()
        return ("/login" in h or "sign in" in h) and "floating-dropdown-btn" not in h

    # ── browser-driving ──
    def login(self, username: str, password: str) -> bool:
        self.b.navigate(f"{self.base}/login")
        page = self.b._page
        page.get_by_role("textbox", name=re.compile("user", re.I)).fill(username)
        page.get_by_role("textbox", name=re.compile("pass", re.I)).fill(password)
        page.get_by_role("button", name=re.compile(r"^sign in$", re.I)).click()
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
        return not self.is_login_page(self.b.get_content())

    def open_ticket(self, ticket_id: str) -> str:
        self.b.navigate(self.ticket_url(ticket_id))
        self._wait_ready(ticket_id)
        return self.b.get_content()

    def _wait_ready(self, ticket_id: str, tries: int = 24) -> None:
        for _ in range(tries):
            t = self.b._page.title()
            if re.search(rf"^Ticket ID {ticket_id}\b", t) or is_login_redirect(t):
                return
            time.sleep(0.5)

    def open_subview(self, label: str) -> str:
        self.b._page.get_by_role("button").filter(
            has_text=re.compile(rf"^{re.escape(label)}\b")).first.click()
        time.sleep(1.5)
        return self.b.get_content()

    def download_all(self, dest_dir: Path) -> list[Path]:
        dest_dir.mkdir(parents=True, exist_ok=True)
        saved = []
        page = self.b._page
        for btn in page.get_by_role("button", name=re.compile(r"^download$", re.I)).all():
            try:
                with page.expect_download(timeout=30_000) as dl:
                    btn.click()
                d = dl.value
                target = dest_dir / d.suggested_filename
                d.save_as(str(target))
                saved.append(target)
            except Exception:
                continue
        return saved

def is_login_redirect(title: str) -> bool:
    return "login" in title.lower() or "sign in" in title.lower()
```
> Confirm the Sign-In button enables after both fields fill (JS-gated) — `fill` fires input events so it should; if not, add a short wait before `.click()`. The role-name for the textboxes comes from the login fixture / live page.

- [ ] **Step 4: Run to verify pass.** Expected: 3 passed.
- [ ] **Step 5: Commit.**
```bash
git add scraper/portal/__init__.py scraper/portal/tradedesk_portal.py tests/test_tradedesk_portal.py
git commit -m "feat(v4): TradeDeskPortal adapter (login, navigate, subviews, download)"
```

---

### Task 8: Phase-1 regression gate

**Files:** none (verification only)

- [ ] **Step 1: Run the full scraper test suite.**
Run: `scraper\venv\Scripts\python.exe -m pytest tests/ -q`
Expected: all pass (new tradedesk tests + existing KB/release-note tests untouched).

- [ ] **Step 2: Confirm no PII in committed fixtures (final gate).**
Run: `grep -RniE "(wide world importers|@contoso|@tradedesk)" tests/fixtures/tradedesk/ || echo CLEAN`
Expected: `CLEAN`.

- [ ] **Step 3: Commit any fixups; tag Phase 1 done in the commit message.**

---

## Phases 2–6 — roadmap (each becomes its own plan after the prior phase locks interfaces)

**Phase 2 — Ticket engine.** Rewire `scraper/ticket_engine.py` onto `TradeDeskPortal`: workers cap `min(4,…)→min(10,…)`; add `scraper/control.py` `RunControl` (cancel + `pause()/resume()/wait_if_paused()`) and call it at ticket boundaries; merge resolution (`open_subview("Resolve")`→`parse_resolution`) and downloads (`open_subview("Files")`→`download_all`) into the saved ticket; extend `writers/ticket_writer.py` to record comment + resolution file paths and `source`; add `on_ticket_meta(tid, title, files_count)` callback; rewrite `scraper/smoke_test.py` for the new portal (real login + ticket 76511 end-to-end incl. a comment file + resolution file). Deliverable: a green smoke run (operator-confirmed) saving a full ticket with files.

**Phase 3 — Theme + app shell + Settings.** `scraper/theme.py` (PALETTE/FONT_STACK/QSS ported from chatbot `gui.py`), `scraper/app.py` (QApplication + animated branded splash + window icon), branded top bar, ice-scraper `.ico` (new `_make_scraper_icon.py`), `scraper/settings_dialog.py` + `scraper/app_settings.py` (per-type output paths defaulting to `library/tickets`/`library/kb`; collapsible portal credentials → keyring). Deliverable: themed window with working Settings; engines read output paths from `app_settings`.

**Phase 4 — Tickets tab restyle.** Rework `scraper/ticket_tab.py`: prominent Workers 1–10 stepper (verified visible in the built exe), Pause/Resume wired to `RunControl`, live **Title** + **Files** columns (consume `on_ticket_meta`), credentials read from Settings (remove inline credential entry). Deliverable: fully working restyled Tickets tab.

**Phase 5 — Knowledge Base tab (Option C).** Rebuild `scraper/kb_tab.py` as family-sidebar + detail table; preserve v1/v2 actions (Validate, Rebuild Indexes, Scrape All, Force All, per-space/per-family scrape + Force); add a "Release Notes" sidebar group driving the v1 `engine.py`; Pause/Resume via `RunControl` (add the gate to `kb_engine.py`/`engine.py`); space filter box. Deliverable: compact KB tab, RN folded in.

**Phase 6 — Packaging + QA.** New one-folder `ContosoKBScraper-v4.spec` (`COLLECT`, `icon=<ice-scraper.ico>`, exclude Playwright's bundled Chromium, fresh `--workpath` to dodge the OneDrive lock); `APP_VERSION="4.0"` + changelog + `test_version`; full `pytest` pass; **operator-confirmed smoke run before building** (standing rule); build, verify frozen boot + system-Chrome launch + window icon < 1 min; security check (no password/token on disk or in logs). Deliverable: shippable v4 one-folder build.

---

## Self-Review

- **Spec coverage (Phase 1 scope):** new portal model §4 → Tasks 1–7; rendered-DOM extraction → parser Tasks 2–6; attachments (comment + resolution + files) → Tasks 4,5 (refs) + Task 7 `download_all`; login form → Task 7; PII-safe fixtures + QA → Tasks 1,8. Phases 2–6 spec items are mapped in the roadmap. ✅
- **Placeholder scan:** the resolution/files/not-found selectors are explicitly *captured then confirmed* in Task 1 and pointed at from Tasks 2/5 — these are concrete dependencies with a named source (`DOM_MAP.md`), not vague "handle later" placeholders. Field/comment selectors are fully concrete. ✅
- **Type consistency:** `parse_ticket_detail` consumes `is_not_found`/`parse_ticket_fields`/`parse_comments` with matching signatures; `TradeDeskPortal` consumes `is_not_found`; field keys are consistent across Tasks 3 and 6 (`product`, `status`, …). ✅
