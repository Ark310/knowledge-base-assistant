# KB Scraper v4.0.1 — Phase 3: Legacy (contoso) Portal Tab at Parity — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Task 5 is an interactive live verification driven by the controller via keyring creds.

**Goal:** Add a **Legacy** ticket tab that scrapes the old ASP.NET portal **support.contoso.example** at full parity with the tradedesk tab — ticket fields, comments, comment images, files, and the resolution (text + its thread + files) — reusing the async engine and the canonical schema.

**Architecture:** The async engine is already portal-agnostic (it drives any object implementing the `AsyncPortal` contract + a `parse_fn`). Phase 3 adds a **contoso async adapter** (`contoso_portal.py`) and a **contoso parser** (`contoso_parser.py`, revived from commit `a718c81` and raised to the canonical schema). The ASP.NET flow maps onto the existing interface: `open_ticket`→`edit_bug.aspx`, `subview_count("Resolve")`→1 iff the detail page shows `resolution(filled)`, `open_subview("Resolve")`→`Resolution.aspx`, `Files`→0 / `download_all`→[] (legacy embeds images inline as base64, decoded by the writer). The only engine change is making the resolution parser injectable. The Legacy tab reuses `TicketTab`/`AsyncTicketWorker` parameterized by a `portal_kind`. Same keyring login works on both portals.

**Tech Stack:** async Playwright (system Chrome), BeautifulSoup, PySide6, pytest. Test interpreter `scraper\venv\Scripts\python.exe`. Builds on Phase 2 (branch `feat/kb-scraper-v4.0.1`, head `cfcdf78`).

## Global Constraints
- Password → OS keyring only; never on disk, never logged, never in process args. Same creds work on both portals.
- No PII/secrets in logs — exception **type** only; never dump ticket HTML to disk (it carries PII).
- System Chrome via `channel="chrome"`; no bundled browser.
- Canonical ticket schema (base_portal.empty_ticket): `ticket_id, title, url, fields-flat, comments[{id,author,date,internal,body,images:[{mime,saved_path}],attachments:[{label,saved_path}]}], resolution{text,comments[],attachments[]}, attachments[]`. Raw base64 never in JSON (writer scrubs comments AND resolution.comments — already in place).
- Light mode stays default for BOTH tabs; multi-window toggle applies to both.
- Do NOT change the tradedesk adapter/parser behavior, the KB engines, or the sync engine.
- Legacy portal default URL = `https://support.contoso.example`.
- Old-portal selectors come from `a718c81` (still the live legacy portal); CONFIRM/fix them against the real DOM in Task 5 before declaring parity.

## Legacy portal facts (from commit a718c81, confirmed 2026-06-09)
- Login: navigate base; fill `#user` + `#pw`; submit. Login page = HTML contains both `id="user"` AND `id="pw"`.
- Detail: `{base}/edit_bug.aspx?id={tid}` — fields in `<tr><td>` rows via `_LABEL_MAP`; comments are `<tr>` rows whose `cells[0]` has exactly 2 direct `<table>` children (table[0]=meta header "comment N posted by…", table[1]=body); inline screenshots are base64 `<img>` inside `<span class="cmt_text">`.
- Resolution: present iff detail HTML contains `resolution(filled)` (the `<li id="resolution">` text); page `{base}/Resolution.aspx?bugid={tid}`, text in `textarea#txtDescription` (fallback: a textarea in `form#resolutionForm`).

---

### Task 1: Make the resolution parser injectable in the async engine

**Files:** Modify `scraper/ticket_engine_async.py`; Test `tests/test_ticket_engine_async.py` (add 1 case).

**Interfaces:**
- Produces: `run_ticket_scrape_async(..., parse_fn=parse_ticket_detail, parse_resolution_fn=parse_resolution, mode="light")` — `_fetch_ticket` uses `parse_resolution_fn` instead of the hardcoded `parse_resolution`. Default preserves tradedesk behavior.

- [ ] **Step 1: Write the failing test** (append to `tests/test_ticket_engine_async.py`) — a custom resolution parser is honored when the portal reports Resolve>0. Use a fake portal whose `subview_count("Resolve")` returns 1 and `open_subview` returns a marker; assert the injected parser ran:
```python
def test_resolution_parser_is_injectable(tmp_path):
    seen = {}
    class ResPortal:
        base = "https://x"
        def __init__(self, page): self.page = page
        def ticket_url(self, t): return f"{self.base}/{t}"
        def is_login_page(self, h): return False
        def is_not_found(self, h, t): return False
        async def login(self, u, p): return True
        async def open_ticket(self, t): return f"<html>{t}</html>"
        async def subview_count(self, label): return 1 if label == "Resolve" else 0
        async def open_subview(self, label, ready_selector=None): return "RESHTML"
        async def download_all(self, dest): return []
    def my_parse(html, tid, base): return {**empty_ticket(tid, base), "title": tid}
    def my_res(html): seen["html"] = html; return {"text": "R", "comments": [], "attachments": []}
    rec = {}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ["7"], force=True, control=RunControl(), cb=_cb(rec),
        workers=1, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=lambda page: ResPortal(page),
        login_once=lambda b, u, p: _true(), parse_fn=my_parse, parse_resolution_fn=my_res, mode="light"))
    assert seen.get("html") == "RESHTML"          # injected resolution parser was used
    assert dict(rec["tickets"])["7"] == "ok"
```
  Add a tiny coroutine helper at the top of the file if not present:
```python
async def _true(): return True
```
  (and use `login_once=lambda b,u,p: _true()` — i.e. a callable returning an awaitable.) If the existing tests pass `login_once` as `async def`, define `async def _login_ok(b,u,p): return True` and use that instead — match the file's style.
- [ ] **Step 2: Run → fail** (`parse_resolution_fn` is not a parameter yet).
- [ ] **Step 3: Implement.** In `scraper/ticket_engine_async.py`:
  - Add `parse_resolution_fn=parse_resolution` to the `run_ticket_scrape_async` signature (keep `parse_fn=parse_ticket_detail`).
  - Pass it into `_fetch_ticket(...)` and change `_fetch_ticket`'s signature to accept `parse_resolution_fn`, replacing the call `data["resolution"] = parse_resolution(res_html)` with `data["resolution"] = parse_resolution_fn(res_html)`.
  - Update the single call site inside the worker: `res = await _fetch_ticket(portal, tid, output_dir, cb, parse_fn, parse_resolution_fn)`.
- [ ] **Step 4: Run → pass** the new test + the whole async-engine file (all existing pass).
- [ ] **Step 5: Full suite** (expect 207 + 1 = 208).
- [ ] **Step 6: Commit** `git add scraper/ticket_engine_async.py tests/test_ticket_engine_async.py && git commit -m "feat(v4.0.1): injectable resolution parser in async engine (portal-agnostic)"`

---

### Task 2: contoso parser (revived → canonical schema)

**Files:** Create `scraper/parsers/contoso_parser.py`; Create `tests/fixtures/contoso/` PII-free fixtures; Test `tests/test_contoso_parser.py`.

**Interfaces:**
- Produces: `parse_ticket_detail(html, ticket_id, portal_url) -> dict` (canonical: `ticket_id, title, url, flat fields, comments[...]` with inline base64 images in `images:[{mime,data}]`), `parse_resolution(html) -> {"text","comments","attachments"}`, `is_not_found(html, ticket_id) -> bool`.

- [ ] **Step 1: Recover the legacy parser as the starting point:**
```
git show a718c81:scraper/parsers/ticket_parser.py > scraper/parsers/contoso_parser.py
```
- [ ] **Step 2: Adapt it to the canonical schema** (read the recovered file, then edit):
  - `parse_ticket_detail`: keep the `_LABEL_MAP`/tr-cells field extraction and `_extract_comments`. Ensure the returned dict uses key **`ticket_id`** (not `id`), includes `title`, `url`, the flat fields, and `comments` where each comment is `{id, author, date, internal, body, images:[{mime,data}], attachments:[]}`. The legacy `_extract_comments` already pulls inline base64 `<img>` from `<span class="cmt_text">` — emit them as `images:[{"mime":..., "data": <b64>}]` (the shared writer decodes them; do NOT keep raw base64 anywhere else). Add an empty `resolution` (`{"text":"","comments":[],"attachments":[]}`) and `attachments: []` so the skeleton matches `base_portal.empty_ticket`.
  - `parse_resolution`: change the return from a bare string to **`{"text": <text>, "comments": <thread or []>, "attachments": <files or []>}`**. Extract the resolution text (textarea#txtDescription / form#resolutionForm fallback). If the Resolution page renders a comment thread (same markup as detail comments) capture it via the comment extractor; otherwise `comments=[]`. Inline base64 images in the resolution go into `resolution.comments[].images` if they belong to thread entries, else leave for live confirmation (Task 5).
  - `is_not_found`: keep as recovered.
  - Remove anything tradedesk-specific that slipped in; keep it pure (no I/O).
- [ ] **Step 3: Create PII-free fixtures** under `tests/fixtures/contoso/`: `ticket_detail.html` (a synthetic edit_bug.aspx with 2 fields, 2 comment rows — one carrying a tiny base64 `<img>` in `<span class="cmt_text">`, the `resolution(filled)` marker), `resolution.html` (Resolution.aspx with `textarea#txtDescription` text), `not_found.html`. Author fake content only (no real ticket data).
- [ ] **Step 4: Write `tests/test_contoso_parser.py`** asserting: fields parsed; `ticket_id` key present; comments count + one comment carries an inline image (`images[0]["data"]` is base64); resolution returns a dict with `text` non-empty + `comments`/`attachments` keys present; `is_not_found` true on the not-found fixture, false on detail.
- [ ] **Step 5: Run → pass** `scraper\venv\Scripts\python.exe -m pytest tests/test_contoso_parser.py -v`. Full suite (expect 208 + N).
- [ ] **Step 6: Commit** `git add scraper/parsers/contoso_parser.py tests/test_contoso_parser.py tests/fixtures/contoso/ && git commit -m "feat(v4.0.1): contoso (legacy ASP.NET) parser revived to canonical schema + PII-free fixtures"`

---

### Task 3: contoso async adapter

**Files:** Create `scraper/portal/contoso_portal.py`; Test: pure helpers unit-tested; browser methods covered by the Task 5 live verification (mirrors the tradedesk adapter).

**Interfaces:**
- Consumes: `AsyncBrowser` (page-bound), `contoso_parser.is_not_found`, `base_portal` helpers.
- Produces: `class AsyncContosoPortal` implementing `AsyncPortal` for the ASP.NET portal; `contoso_login_once(browser, username, password) -> bool`; `make_factory(base) -> (page -> AsyncContosoPortal)`. Pure `ticket_url`, `is_login_page`, `is_not_found` are unit-tested.

- [ ] **Step 1: Write unit tests** `tests/test_contoso_portal.py` for the pure helpers:
```python
def test_ticket_url():
    from scraper.portal.contoso_portal import AsyncContosoPortal
    p = AsyncContosoPortal(None, "https://support.contoso.example/")
    assert p.ticket_url("76511") == "https://support.contoso.example/edit_bug.aspx?id=76511"

def test_is_login_page():
    from scraper.portal.contoso_portal import AsyncContosoPortal
    p = AsyncContosoPortal(None, "https://support.contoso.example")
    assert p.is_login_page('<input id="user"><input id="pw">') is True
    assert p.is_login_page('<table>edit_bug fields</table>') is False
```
- [ ] **Step 2: Implement** `scraper/portal/contoso_portal.py`:
```python
"""Async adapter for the legacy ASP.NET portal support.contoso.example. Page-bound.
Login #user/#pw; detail edit_bug.aspx; resolution Resolution.aspx (only when the
detail page shows 'resolution(filled)'). Legacy embeds images inline as base64
(handled by the parser + writer), so there is no Files sub-view / download_all."""
from __future__ import annotations
import logging
from pathlib import Path
from scraper.parsers.contoso_parser import is_not_found as _is_not_found

log = logging.getLogger("scraper")

def _looks_like_login(html: str) -> bool:
    h = (html or "").lower()
    return ('id="user"' in h) and ('id="pw"' in h)

async def contoso_login_once(browser, username: str, password: str) -> bool:
    base = browser.base
    page = await browser.new_page()
    try:
        await page.goto(base, wait_until="domcontentloaded")
        html = await page.content()
        if not _looks_like_login(html):
            return True                      # already authenticated (cookie)
        await page.fill("#user", username)
        await page.fill("#pw", password)
        # submit: press Enter in the password field (ASP.NET form post)
        await page.press("#pw", "Enter")
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1500)
        return not _looks_like_login(await page.content())
    finally:
        await page.close()

class AsyncContosoPortal:
    def __init__(self, page, base: str):
        self.page = page
        self.base = base.rstrip("/")
        self._last_html = ""
    def ticket_url(self, tid: str) -> str:
        return f"{self.base}/edit_bug.aspx?id={tid}"
    def is_login_page(self, html: str) -> bool:
        return _looks_like_login(html)
    def is_not_found(self, html: str, tid: str) -> bool:
        return _is_not_found(html, tid)
    async def login(self, username, password) -> bool:   # multi-window mode per-worker login
        return True
    async def open_ticket(self, tid: str) -> str:
        await self.page.goto(self.ticket_url(tid), wait_until="domcontentloaded")
        await self.page.wait_for_timeout(800)
        self._last_html = await self.page.content()
        return self._last_html
    async def subview_count(self, label: str) -> int:
        # Resolve = 1 iff the detail page action bar shows 'resolution(filled)'. No Files sub-view.
        if label.lower().startswith("resolve"):
            return 1 if "resolution(filled)" in (self._last_html or "").lower() else 0
        return 0
    async def open_subview(self, label: str, ready_selector: str | None = None) -> str:
        if not label.lower().startswith("resolve"):
            return ""
        # tid is embedded in the current detail URL (edit_bug.aspx?id=NN)
        import re
        m = re.search(r"[?&]id=(\d+)", self.page.url)
        tid = m.group(1) if m else ""
        await self.page.goto(f"{self.base}/Resolution.aspx?bugid={tid}", wait_until="domcontentloaded")
        await self.page.wait_for_timeout(600)
        return await self.page.content()
    async def download_all(self, dest_dir: Path) -> list[Path]:
        return []   # legacy uses inline base64 images (parser+writer); confirm in Task 5

def make_factory(base: str):
    return lambda page: AsyncContosoPortal(page, base)
```
- [ ] **Step 3: Run** `scraper\venv\Scripts\python.exe -m pytest tests/test_contoso_portal.py -v` + import check.
- [ ] **Step 4: Commit** `git add scraper/portal/contoso_portal.py tests/test_contoso_portal.py && git commit -m "feat(v4.0.1): contoso async adapter (login/edit_bug/Resolution.aspx; inline-image model)"`

---

### Task 4: portal_kind wiring + Legacy tab

**Files:** Modify `scraper/async_runner.py` (portal_kind selects wiring), `scraper/ticket_tab.py` (portal_kind + default URL), `scraper/gui.py` (add the Legacy tab); Test `tests/test_async_runner.py` + `tests/test_ticket_tab.py` + `tests/test_app_shell.py` (adjust tab count). READ each file first.

**Interfaces:**
- Produces: `AsyncTicketWorker(..., portal_kind="tradedesk")` — when `browser_factory` is None, `run()` picks the wiring by `portal_kind`: `tradedesk` → tradedesk make_factory/login + default `parse_fn`/`parse_resolution_fn`; `contoso` → contoso make_factory/`contoso_login_once`/`contoso_parser.parse_ticket_detail`/`contoso_parser.parse_resolution`. `TicketTab(portal_kind="tradedesk", default_url=...)` constructs the worker with that kind and uses the matching portal URL.

- [ ] **Step 1: async_runner.** Add `portal_kind="tradedesk"` to `AsyncTicketWorker.__init__`; in `run()`'s real-wiring branch (`if bf is None`), select per `portal_kind`:
  - tradedesk: `from scraper.portal.tradedesk_portal_async import make_factory, tradedesk_login_once`; `ppf=make_factory(url); login=tradedesk_login_once` (parse defaults).
  - contoso: `from scraper.portal.contoso_portal import make_factory as ds_factory, contoso_login_once`; `from scraper.parsers.contoso_parser import parse_ticket_detail as ds_detail, parse_resolution as ds_res`; `ppf=ds_factory(url); login=contoso_login_once`; pass `parse_fn=ds_detail, parse_resolution_fn=ds_res` into `run_ticket_scrape_async`. (Thread `parse_resolution_fn` through the kwargs the same way `parse_fn` is.)
- [ ] **Step 2: ticket_tab.** Add `portal_kind="tradedesk"` + an optional `default_url` to `TicketTab.__init__`. In `_start`, use the portal URL for this tab (tradedesk → `ticket_settings` URL; contoso → `https://support.contoso.example`) and pass `portal_kind=self._portal_kind` to `AsyncTicketWorker`. Credentials come from the SAME keyring (`ticket_settings`) for both. Keep all existing behavior for the default tradedesk tab.
- [ ] **Step 3: gui.py.** Add a third tab `TicketTab(portal_kind="contoso", default_url="https://support.contoso.example")` titled **"Tickets — Legacy"** (existing tradedesk tab → "Tickets — tradedesk"). `closeEvent` must drain ALL ticket tabs (extend the existing drain to the new tab).
- [ ] **Step 4: Tests.** `test_async_runner.py`: add a case asserting `portal_kind="contoso"` selects the contoso wiring (monkeypatch the contoso factory/login to capture they were used, OR assert via injected fakes). `test_ticket_tab.py`: a `TicketTab(portal_kind="contoso")` constructs offscreen and `_start` passes `portal_kind="contoso"` to the (stubbed) worker. `test_app_shell.py`: update the expected tab set to include "Tickets — Legacy".
- [ ] **Step 5: Run** the three test files + offscreen GUI construct (`gui-ok`). Full suite green.
- [ ] **Step 6: Commit** `git add scraper/async_runner.py scraper/ticket_tab.py scraper/gui.py tests/ && git commit -m "feat(v4.0.1): Legacy (contoso) tickets tab + portal_kind wiring (shared keyring login)"`

---

### Task 5: LIVE verification + cross-portal parity (controller + operator)

Interactive — controller drives via keyring creds (operator may watch). Uses superpowers:systematic-debugging for any selector drift.

- [ ] **Step 1: Full suite green.**
- [ ] **Step 2: Live legacy scrape** — drive a contoso scrape of **76511** then **76091** (light mode, workers=1) via keyring creds (a scratchpad runner like `live_async_smoke.py` but `mode`/portal=contoso). Confirm login works on support.contoso.example and the canonical schema is populated (fields, comments, comment images, resolution text + thread + files where present). Capture failures with COUNT-only diagnostics (no PII/HTML dumps); fix selector drift in `contoso_parser`/`contoso_portal` per systematic-debugging.
- [ ] **Step 3: Cross-portal parity** — for 76511 + 76091, compare the contoso output vs the tradedesk output (both saved earlier): assert the SAME categories are populated (fields present, comments>0 where expected, images where expected, resolution captured). Structural parity (counts), not byte-identical (the two portals render differently). Log the comparison.
- [ ] **Step 4: Multi-window legacy** — quick check: legacy tab at workers=3 multi mode opens separate windows + completes (resource sanity).
- [ ] **Step 5: Final review** (subagent, opus) of the Phase-3 diff (base = Phase-2 head `cfcdf78`): contoso adapter/parser correctness, canonical-schema conformance, no-PII/no-raw-base64, engine injectability change, GUI wiring + close-drain of all tabs, test quality. Fix Critical/Important.
- [ ] **Step 6:** Update ledger + memory; mark Phase 3 complete. No exe build (Phase 4).

---

## Self-Review
- **Spec coverage:** Legacy contoso tab (T4), parser+adapter at parity emitting the canonical schema (T2/T3), engine stays portal-agnostic (T1), cross-portal parity validation (T5). Matches spec Phase 3. ✅
- **Placeholder scan:** T1/T3 carry full code; T2 is a recover-from-a718c81 + concrete canonical-schema adaptations + fixtures (legacy selectors are real, from the commit); T4 specifies the exact wiring selection per portal_kind; T5 is an inherently interactive live procedure. Live-DOM confirmation of legacy selectors is explicitly Task 5 (the selectors are recovered, then verified). ✅
- **Type consistency:** `parse_resolution_fn` threaded engine↔runner; canonical schema (ticket_id + flat fields + resolution{text,comments,attachments}) consistent across contoso_parser ↔ empty_ticket ↔ writer; `make_factory`/`*_login_once` mirror the tradedesk adapter's names; `portal_kind` consistent runner↔tab↔gui. ✅
- **Risk:** the legacy DOM may have drifted since `a718c81` — recovered selectors are the starting point, CONFIRMED/fixed live in Task 5 before parity is claimed. Light mode with ASP.NET concurrent tabs (shared cookie) verified in T5; multi-window is the fallback. No exe build this phase.
