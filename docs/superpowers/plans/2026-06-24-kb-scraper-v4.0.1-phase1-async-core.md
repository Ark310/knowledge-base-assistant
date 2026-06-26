# KB Scraper v4.0.1 — Phase 1: Async Core + New-Portal Light Mode + Live Reliability — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Task 6 is an interactive live session run by the controller + operator, not a subagent.

**Goal:** Replace the per-worker-Chrome ticket engine with an **async Playwright** engine whose default **light mode** runs one Chrome window, one login, and N concurrent tabs — removing the machine-saturation freeze — and live-fix the new portal's reliability so it scrapes dependably.

**Architecture:** A new async stack additive to the existing sync `Browser` (which the KB/RN engines keep using). One asyncio event loop runs N worker coroutines pulling ticket IDs from an `asyncio.Queue`; the v4.0 crash-resilience (bounded redispatch → in-place page rebuild → drain-to-failed → exactly-once terminal) is ported to async. Parsers stay synchronous and emit the canonical ticket dict from the spec. The GUI runs the loop in a worker `QThread` and updates via Qt signals.

**Tech Stack:** `playwright.async_api`, `asyncio`, PySide6 (QThread + signals), BeautifulSoup (existing parsers), pytest + `pytest-asyncio`.

## Global Constraints
- Password → OS keyring only; never on disk, never logged, never in process args. (spec §Security)
- No customer PII/secrets in logs — log exception **type** only, never messages. (spec §Security)
- System Chrome via `channel="chrome"`; no bundled browser. (spec §Security)
- Canonical ticket schema (spec §Architecture) — both portals emit it; raw base64 never in JSON.
- Operator-confirmed live run before any exe build (no build in Phase 1).
- Phase 1 implements **light mode only**; multi-window is Phase 2. Keep `mode` a parameter so Phase 2 slots in.
- Worker count is user-controlled (clamped 1–10).
- Do NOT modify the sync `scraper/core.py Browser` or the KB/RN engines — async work is additive.

---

### Task 1: Canonical schema doc + async portal Protocol + pure helpers

**Files:**
- Create: `scraper/portal/base_portal.py`
- Test: `tests/test_base_portal.py`

**Interfaces:**
- Produces: `TICKET_SCHEMA_KEYS` (tuple), `empty_ticket(tid, url) -> dict`, `AsyncPortal` (typing.Protocol with async methods `login`, `open_ticket`, `subview_count`, `open_subview`, `download_all` and sync `ticket_url`, `is_login_page`, `is_not_found`), and pure helpers `looks_like_login(html) -> bool`.

- [ ] **Step 1: Write the failing test** — `tests/test_base_portal.py`:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.portal import base_portal as bp

def test_empty_ticket_has_canonical_shape():
    t = bp.empty_ticket("76511", "https://x/tickets/76511/edit")
    assert t["id"] == "76511"
    assert t["url"].endswith("/76511/edit")
    assert t["fields"] == {}
    assert t["comments"] == [] and t["attachments"] == []
    assert t["resolution"] == {"text": "", "comments": [], "attachments": []}

def test_looks_like_login_only_when_no_ticket_fields():
    assert bp.looks_like_login("Please sign in") is True
    assert bp.looks_like_login("sign in <button class='floating-dropdown-btn'>") is False
    assert bp.looks_like_login("a fully rendered ticket") is False
```
- [ ] **Step 2: Run → fail** `scraper\venv\Scripts\python.exe -m pytest tests/test_base_portal.py -v` → ModuleNotFoundError.
- [ ] **Step 3: Implement** `scraper/portal/base_portal.py`:
```python
"""Canonical ticket schema + async portal contract shared by both portals."""
from __future__ import annotations
from typing import Protocol, runtime_checkable
from pathlib import Path

TICKET_SCHEMA_KEYS = ("id", "title", "url", "fields", "comments", "resolution", "attachments")

def empty_ticket(ticket_id: str, url: str = "") -> dict:
    """A canonical ticket dict with every key present (the shape both portals emit)."""
    return {
        "id": ticket_id, "title": "", "url": url, "fields": {},
        "comments": [],   # [{author,date,body,images:[{mime,saved_path}],attachments:[{label,saved_path}]}]
        "resolution": {"text": "", "comments": [], "attachments": []},
        "attachments": [],  # [{filename, saved_path}]
    }

def looks_like_login(html: str) -> bool:
    """True when the page looks like the login screen AND no ticket fields are present."""
    h = (html or "").lower()
    return (("sign in" in h) or ("/login" in h)) and "floating-dropdown-btn" not in h

@runtime_checkable
class AsyncPortal(Protocol):
    base: str
    def ticket_url(self, ticket_id: str) -> str: ...
    def is_login_page(self, html: str) -> bool: ...
    def is_not_found(self, html: str, ticket_id: str) -> bool: ...
    async def login(self, username: str, password: str) -> bool: ...
    async def open_ticket(self, ticket_id: str) -> str: ...
    async def subview_count(self, label: str) -> int: ...
    async def open_subview(self, label: str, ready_selector: str | None = None) -> str: ...
    async def download_all(self, dest_dir: Path) -> list[Path]: ...
```
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit** `git add scraper/portal/base_portal.py tests/test_base_portal.py && git commit -m "feat(v4.0.1): canonical ticket schema + async portal protocol + pure helpers"`

---

### Task 2: Async Chrome wrapper

**Files:**
- Create: `scraper/portal/async_browser.py`
- Test: covered by the Task 6 live smoke (thin Playwright wrapper, like the sync `Browser` which also has no unit tests).

**Interfaces:**
- Produces: `class AsyncBrowser` with `async open()`, `async new_page() -> Page`, `async close()`, attribute `context` (shared `BrowserContext`), `headless`/`channel`. One browser, one context (shared cookies = one login); each worker calls `new_page()`.

- [ ] **Step 1: Implement** `scraper/portal/async_browser.py` (port of `core.py Browser` to async; one shared context so all pages share the login):
```python
"""Async Chrome wrapper (system Chrome). One browser + one shared context;
each worker opens its own page (tab) in that context, so login is shared."""
from __future__ import annotations
from playwright.async_api import async_playwright

class AsyncBrowser:
    def __init__(self, headless: bool = False, timeout_ms: int = 30_000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self.context = None

    async def open(self) -> "AsyncBrowser":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless, channel="chrome")
        self.context = await self._browser.new_context(accept_downloads=True)
        self.context.set_default_timeout(self.timeout_ms)
        return self

    async def new_page(self):
        page = await self.context.new_page()
        page.set_default_timeout(self.timeout_ms)
        return page

    async def close(self):
        for closer in (
            lambda: self._browser.close() if self._browser else None,
            lambda: self._pw.stop() if self._pw else None,
        ):
            try:
                res = closer()
                if res is not None:
                    await res
            except Exception:
                pass
```
- [ ] **Step 2: Import check** `scraper\venv\Scripts\python.exe -c "from scraper.portal.async_browser import AsyncBrowser; print('ok')"` → `ok`.
- [ ] **Step 3: Commit** `git add scraper/portal/async_browser.py && git commit -m "feat(v4.0.1): async Chrome wrapper (shared context = one login, page-per-worker)"`

---

### Task 3: Async ticket engine (light mode + crash resilience)

**Files:**
- Create: `scraper/ticket_engine_async.py`
- Test: `tests/test_ticket_engine_async.py`

**Interfaces:**
- Consumes: `RunControl` (scraper/control.py — has `cancelled`, `wait_if_paused()`; add async-friendly check by polling), `TicketEngineCallbacks` (scraper/ticket_engine.py), `base_portal.empty_ticket`, the canonical schema, `save_ticket` (scraper/writers/ticket_writer.py).
- Produces: `async def run_ticket_scrape_async(portal_url, username, password, ticket_ids, *, force=False, control, cb, workers=4, output_dir, page_portal_factory, login_once, mode="light") -> dict`. Reuses `MAX_TICKET_ATTEMPTS`/`MAX_WORKER_REBUILDS` and `parse_ticket_input` from `scraper.ticket_engine`.
- `page_portal_factory(page) -> AsyncPortal` builds a portal bound to a page (injected so tests use a fake). `login_once(browser, username, password) -> bool` performs the single shared-context login (injected/faked in tests).

- [ ] **Step 1: Write the failing tests** — `tests/test_ticket_engine_async.py`. A fake async portal drives the engine with no real browser:
```python
import sys, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.control import RunControl
from scraper import ticket_engine as te          # for callbacks + constants
from scraper import ticket_engine_async as tea
from scraper.portal.base_portal import empty_ticket

class FakeAsyncBrowser:
    def __init__(self): self.pages = 0
    async def open(self): return self
    async def new_page(self):
        self.pages += 1
        return object()      # opaque page handle; the fake portal ignores it
    async def close(self): pass

def _cb(rec):
    return te.TicketEngineCallbacks(
        on_log=lambda l, m: None,
        on_progress=lambda i, n: None,
        on_ticket=lambda tid, st: rec.setdefault("tickets", []).append((tid, st)),
        on_ticket_meta=lambda tid, t, n: rec.setdefault("meta", []).append((tid, t, n)),
        on_finished=lambda rep: rec.update(report=rep),
    )

def make_factory(crash_rule):
    """crash_rule(tid, prior_crashes)->bool. Shared crash counts across rebuilt portals."""
    crashes = {}
    class FakePortal:
        base = "https://x"
        def __init__(self, page): self.page = page
        def ticket_url(self, tid): return f"{self.base}/tickets/{tid}/edit"
        def is_login_page(self, html): return False
        def is_not_found(self, html, tid): return tid == "404"
        async def login(self, u, p): return True
        async def open_ticket(self, tid):
            n = crashes.get(tid, 0)
            if crash_rule(tid, n):
                crashes[tid] = n + 1
                raise RuntimeError("simulated tab crash")
            return f"<html>{tid}</html>"
        async def subview_count(self, label): return 0
        async def open_subview(self, label, ready_selector=None): return ""
        async def download_all(self, dest): return []
    return (lambda page: FakePortal(page)), crashes

def run(ids, workers, crash_rule, tmp_path, force=True, monkeyparse=True):
    rec = {}
    factory, crashes = make_factory(crash_rule)
    async def login_once(browser, u, p): return True
    # parse returns a minimal canonical ticket so save_ticket writes a file
    def fake_parse(html, tid, base):
        return None if "404" in html else {**empty_ticket(tid, f"{base}/{tid}"), "title": f"T{tid}"}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ids, force=force, control=RunControl(), cb=_cb(rec),
        workers=workers, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=factory, login_once=login_once, parse_fn=fake_parse, mode="light"))
    return rec, crashes

def test_all_tickets_reach_terminal_ok(tmp_path):
    rec, _ = run(["1", "2", "3"], 2, lambda tid, n: False, tmp_path)
    assert {t for t, _ in rec["tickets"]} == {"1", "2", "3"}
    assert all(st == "ok" for _, st in rec["tickets"])
    assert rec["report"]["saved"] == 3

def test_transient_crash_redispatched_then_ok(tmp_path):
    rec, crashes = run(["1", "2"], 2, lambda tid, n: tid == "1" and n == 0, tmp_path)
    assert dict(rec["tickets"])["1"] == "ok"
    assert crashes["1"] == 1

def test_permanent_crash_failed_not_stranded(tmp_path):
    rec, crashes = run(["1", "BAD", "2"], 2, lambda tid, n: tid == "BAD", tmp_path)
    s = dict(rec["tickets"])
    assert s["1"] == "ok" and s["2"] == "ok" and s["BAD"] == "failed"
    assert len(rec["tickets"]) == 3
    assert crashes["BAD"] == te.MAX_TICKET_ATTEMPTS

def test_all_workers_die_drains_to_failed(tmp_path):
    rec, _ = run(["1", "2", "3"], 2, lambda tid, n: True, tmp_path)
    assert all(st == "failed" for _, st in rec["tickets"])
    assert len(rec["tickets"]) == 3
```
- [ ] **Step 2: Run → fail** (`run_ticket_scrape_async` undefined).
- [ ] **Step 3: Implement** `scraper/ticket_engine_async.py`. Light mode: one browser, one shared-context login, N worker coroutines each own a page; the v4.0 resilience ported to asyncio. The fetch helper reads sub-view counts and downloads exactly like the sync engine.
```python
"""Async ticket engine — light mode (1 browser, 1 login, N tabs). Crash-resilient:
shared asyncio.Queue, bounded redispatch, in-place page rebuild, drain-to-failed,
exactly-once terminal status. Logs exception TYPE only (no PII)."""
from __future__ import annotations
import asyncio
from pathlib import Path

from scraper.ticket_engine import (
    MAX_TICKET_ATTEMPTS, MAX_WORKER_REBUILDS, TicketEngineCallbacks,
    parse_ticket_input, _load_scraped, _mark_scraped, _match_paths, TICKETS_DIR,
)
from scraper.parsers.ticket_parser import parse_ticket_detail, parse_resolution
from scraper.writers.ticket_writer import save_ticket

_SESSION_EXPIRED = object()

async def _fetch_ticket(portal, tid, output_dir, cb, parse_fn) -> dict | str | object | None:
    html = await portal.open_ticket(tid)
    if portal.is_login_page(html):
        return _SESSION_EXPIRED
    if portal.is_not_found(html, tid):
        cb.on_log("info", f"[NOT FOUND] #{tid}")
        return "not_found"
    data = parse_fn(html, tid, portal.base)
    if not data:
        cb.on_log("warning", f"#{tid}: parser returned empty — skipping.")
        return None
    resolve_n = await portal.subview_count("Resolve")
    files_n = await portal.subview_count("Files")
    cb.on_log("info", f"#{tid}: sub-views — Resolve={resolve_n}, Files={files_n}")
    if resolve_n > 0:
        res_html = await portal.open_subview("Resolve", ready_selector="div.resolution-container")
        data["resolution"] = parse_resolution(res_html)
    saved: list[Path] = []
    if files_n > 0:
        await portal.open_subview("Files", ready_selector='button[title*="Download"]')
        saved = await portal.download_all(Path(output_dir) / "attachments" / tid)
        cb.on_log("info", f"#{tid}: downloaded {len(saved)} file(s)")
    data["attachments"] = [{"filename": p.name, "saved_path": str(p)} for p in saved]
    by_name = {p.name: p for p in saved}
    for c in data.get("comments") or []:
        _match_paths(c.get("attachments"), by_name)
    if isinstance(data.get("resolution"), dict):
        _match_paths(data["resolution"].get("attachments"), by_name)
    return data

async def run_ticket_scrape_async(
    portal_url, username, password, ticket_ids, *,
    force=False, control, cb: TicketEngineCallbacks | None = None,
    workers=4, output_dir=None, browser_factory, page_portal_factory,
    login_once, parse_fn=parse_ticket_detail, mode="light",
) -> dict:
    cb = cb or TicketEngineCallbacks()
    workers = max(1, min(10, int(workers or 1)))
    output_dir = Path(output_dir) if output_dir else TICKETS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    already = _load_scraped()
    total = len(ticket_ids)
    stats = {"total": total, "saved": 0, "skipped": 0, "not_found": 0, "failed": 0, "retried": 0}

    pending: asyncio.Queue = asyncio.Queue()
    for t in ticket_ids:
        pending.put_nowait(t)
    attempts: dict[str, int] = {}
    finished: set[str] = set()
    lock = asyncio.Lock()
    progress = [0]
    state_lock = asyncio.Lock()

    async def terminal(tid, status, key, meta=None):
        async with lock:
            if tid in finished:
                return
            finished.add(tid); stats[key] += 1; progress[0] += 1; p = progress[0]
        cb.on_progress(p, total); cb.on_ticket(tid, status)
        if meta is not None:
            cb.on_ticket_meta(*meta)

    browser = await browser_factory().open()
    try:
        if not await login_once(browser, username, password):
            cb.on_log("error", "Login failed; aborting.")
            while not pending.empty():
                await terminal(pending.get_nowait(), "failed", "failed")
            cb.on_finished(stats); return stats

        async def worker(idx):
            prefix = f"[W{idx + 1}] " if workers > 1 else ""
            page = await browser.new_page()
            portal = page_portal_factory(page)
            rebuilds = 0
            try:
                while True:
                    control.wait_if_paused()
                    if control.cancelled:
                        cb.on_log("warning", f"{prefix}Cancelled."); break
                    try:
                        tid = pending.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    async with lock:
                        if tid in finished:
                            continue
                    if not force and tid in already:
                        cb.on_log("info", f"{prefix}[SKIP] #{tid}")
                        await terminal(tid, "skipped", "skipped"); continue
                    async with lock:
                        attempts[tid] = attempts.get(tid, 0) + 1
                        n = attempts[tid]
                    try:
                        res = await _fetch_ticket(portal, tid, output_dir, cb, parse_fn)
                        if res is _SESSION_EXPIRED:
                            cb.on_log("warning", f"{prefix}#{tid}: session expired"); raise RuntimeError("session expired")
                        if res is None:
                            await terminal(tid, "failed", "failed")
                        elif res == "not_found":
                            await terminal(tid, "not_found", "not_found")
                        else:
                            save_ticket(res, output_dir)
                            async with state_lock:
                                _mark_scraped(tid); already.add(tid)
                            await terminal(tid, "ok", "saved",
                                meta=(tid, res.get("title", ""), len(res.get("attachments") or [])))
                            cb.on_log("info", f"{prefix}[OK] #{tid}: {res.get('title') or ''}")
                    except Exception as exc:
                        if n < MAX_TICKET_ATTEMPTS:
                            cb.on_log("warning", f"{prefix}#{tid}: worker error ({type(exc).__name__}) "
                                                 f"— redispatching ({n}/{MAX_TICKET_ATTEMPTS}).")
                            pending.put_nowait(tid)
                        else:
                            cb.on_log("error", f"{prefix}#{tid}: failed after {n} ({type(exc).__name__}).")
                            await terminal(tid, "failed", "failed")
                        rebuilds += 1
                        try: await page.close()
                        except Exception: pass
                        if rebuilds > MAX_WORKER_REBUILDS:
                            cb.on_log("error", f"{prefix}too many crashes — worker exiting."); page = None; break
                        try:
                            page = await browser.new_page(); portal = page_portal_factory(page)
                        except Exception:
                            cb.on_log("error", f"{prefix}page rebuild failed — worker exiting."); page = None; break
            finally:
                if page is not None:
                    try: await page.close()
                    except Exception: pass

        cb.on_log("info", f"--- Starting ticket scrape: {total} tickets"
                          + (f" ({workers} workers, {mode})" if workers > 1 else "") + " ---")
        n_workers = max(1, min(workers, total)) if total else 0
        await asyncio.gather(*(worker(i) for i in range(n_workers)))

        if not control.cancelled:
            while not pending.empty():
                tid = pending.get_nowait()
                cb.on_log("error", f"#{tid}: not processed (all workers stopped) — marked failed.")
                await terminal(tid, "failed", "failed")
        async with lock:
            stats["retried"] = sum(1 for c in attempts.values() if c > 1)
        if total and stats["failed"] == total:
            cb.on_log("error", f"All {total} tickets failed — check credentials/network/portal.")
    finally:
        await browser.close()
    cb.on_finished(stats)
    return stats
```
- [ ] **Step 4: Run → pass** `scraper\venv\Scripts\python.exe -m pytest tests/test_ticket_engine_async.py -v`. (If pytest-asyncio is needed it is not — tests use `asyncio.run`.)
- [ ] **Step 5: Run 5× for flakiness** `for /l %i in (1,1,5) do scraper\venv\Scripts\python.exe -m pytest tests/test_ticket_engine_async.py -q` (PowerShell: `1..5 | % { ... }`). All pass.
- [ ] **Step 6: Commit** `git add scraper/ticket_engine_async.py tests/test_ticket_engine_async.py && git commit -m "feat(v4.0.1): async ticket engine — light mode, shared queue, crash-resilient (ported from sync)"`

---

### Task 4: Async tradedesk adapter

**Files:**
- Create: `scraper/portal/tradedesk_portal_async.py`
- Test: covered by Task 6 live smoke (Playwright-driving; the sync version has none either).

**Interfaces:**
- Produces: `class AsyncTradeDeskPortal` bound to a **page** (constructed by `page_portal_factory(page)`), implementing `AsyncPortal`. Plus module-level `async def tradedesk_login_once(browser, username, password) -> bool` that logs in once on the shared context (used as `login_once`), and `make_factory(base) -> (page->AsyncTradeDeskPortal)`.

- [ ] **Step 1: Implement** by porting `scraper/portal/tradedesk_portal.py` method-for-method to async (this is a mechanical translation — `def`→`async def`, add `await`, `page.wait_for_timeout`→`await page.wait_for_timeout`, `expect_download` async form). Keep every selector, regex, comment, and the `_unique_path` helper identical (copy it). The portal operates on the page it is given; `login_once` runs once on a throwaway page in the shared context so all worker pages inherit the cookie:
```python
"""Async adapter for portal.contoso.example SPA. Page-bound (one page per worker tab).
Selectors/timing identical to the sync TradeDeskPortal; login happens once per context."""
from __future__ import annotations
import re
from pathlib import Path
from scraper.parsers.ticket_parser import is_not_found as _is_not_found
from scraper.portal.base_portal import looks_like_login

def _unique_path(dest_dir: Path, name: str) -> Path:
    name = name or "file"
    target = dest_dir / name
    if not target.exists():
        return target
    stem, dot, ext = name.rpartition(".")
    base, suffix = (stem, f".{ext}") if dot else (name, "")
    i = 1
    while (cand := dest_dir / f"{base}_{i}{suffix}").exists():
        i += 1
    return cand

async def tradedesk_login_once(browser, username: str, password: str) -> bool:
    """Log in once on the shared context (a throwaway page); cookie shared by all tabs."""
    base = browser.base  # set by make_factory wiring below
    page = await browser.new_page()
    try:
        await page.goto(f"{base}/login", wait_until="domcontentloaded")
        await page.get_by_role("textbox", name=re.compile("user", re.I)).fill(username)
        await page.get_by_role("textbox", name=re.compile("pass", re.I)).fill(password)
        await page.get_by_role("button", name=re.compile(r"^\s*sign in\s*$", re.I)).click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2_000)
        html = await page.content()
        return not looks_like_login(html)
    finally:
        await page.close()

class AsyncTradeDeskPortal:
    def __init__(self, page, base: str):
        self.page = page
        self.base = base.rstrip("/")
    def ticket_url(self, tid: str) -> str:
        return f"{self.base}/tickets/{tid}/edit"
    def is_login_page(self, html: str) -> bool:
        return looks_like_login(html)
    def is_not_found(self, html: str, tid: str) -> bool:
        return _is_not_found(html, tid)
    async def login(self, username, password) -> bool:   # multi-window mode (Phase 2) uses this
        return True
    async def open_ticket(self, tid: str) -> str:
        await self.page.goto(self.ticket_url(tid), wait_until="domcontentloaded")
        await self.page.wait_for_timeout(1_500)
        if f"/tickets/{tid}/edit" not in self.page.url:
            return await self.page.content()
        for sel in ("button.floating-dropdown-btn", "button.sidebar-menu-btn"):
            try:
                await self.page.wait_for_selector(sel, timeout=20_000)
            except Exception:
                pass
        await self.page.wait_for_timeout(500)
        return await self.page.content()
    async def subview_count(self, label: str) -> int:
        loc = self.page.locator("button.sidebar-menu-btn",
            has_text=re.compile(rf"^\s*{re.escape(label)}\b", re.I)).first
        try:
            txt = await loc.inner_text(timeout=3_000)
        except Exception:
            return 0
        m = re.search(r"(\d+)", txt)
        return int(m.group(1)) if m else 0
    async def _click_subview(self, label: str) -> bool:
        btn = self.page.locator("button.sidebar-menu-btn",
            has_text=re.compile(rf"^\s*{re.escape(label)}\b", re.I)).first
        try:
            await btn.click(timeout=5_000); return True
        except Exception:
            return False
    async def open_subview(self, label: str, ready_selector: str | None = None) -> str:
        if not await self._click_subview(label):
            return await self.page.content()
        if ready_selector:
            try:
                await self.page.wait_for_selector(ready_selector, timeout=15_000)
            except Exception:
                pass
        await self.page.wait_for_timeout(500)
        return await self.page.content()
    async def download_all(self, dest_dir: Path) -> list[Path]:
        dest_dir = Path(dest_dir); dest_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        try:
            await self.page.wait_for_selector('button[title*="Download"]', timeout=10_000)
        except Exception:
            return saved
        for btn in await self.page.locator('button[title*="Download"]').all():
            try:
                async with self.page.expect_download(timeout=30_000) as dl:
                    await btn.click()
                d = await dl.value
                target = _unique_path(dest_dir, d.suggested_filename)
                await d.save_as(str(target))
                saved.append(target)
            except Exception:
                continue
        return saved

def make_factory(base: str):
    """Returns page->AsyncTradeDeskPortal for the engine's page_portal_factory."""
    return lambda page: AsyncTradeDeskPortal(page, base)
```
  NOTE for implementer: wire `browser.base` in Task 5 (set `browser.base = portal_url` after constructing the AsyncBrowser) so `tradedesk_login_once` can read it; or change the engine call to pass base explicitly. Keep whichever is cleaner — document the choice.
- [ ] **Step 2: Import check** `scraper\venv\Scripts\python.exe -c "from scraper.portal.tradedesk_portal_async import AsyncTradeDeskPortal, tradedesk_login_once, make_factory; print('ok')"`.
- [ ] **Step 3: Commit** `git add scraper/portal/tradedesk_portal_async.py && git commit -m "feat(v4.0.1): async tradedesk adapter (page-bound, one-login-per-context)"`

---

### Task 5: GUI light-mode wiring (async loop in a worker QThread)

**Files:**
- Modify: `scraper/ticket_tab.py` (run the async engine instead of the sync one)
- Create: `scraper/async_runner.py` (QThread that owns the asyncio loop and bridges callbacks→Qt signals)
- Test: `tests/test_async_runner.py` (offscreen; drive the runner with a trivial coroutine, assert signals fire)

**Interfaces:**
- Consumes: `run_ticket_scrape_async`, `AsyncBrowser`, `tradedesk_portal_async.make_factory`/`tradedesk_login_once`, `RunControl`, `app_settings.tickets_dir()`, creds from `ticket_settings`.
- Produces: `class AsyncTicketWorker(QThread)` with signals `log(str,str)`, `progress(int,int)`, `ticket(str,str)`, `ticket_meta(str,str,int)`, `finished_report(dict)`; constructed with the run parameters; `run()` does `asyncio.run(run_ticket_scrape_async(... cb=<signal-emitting callbacks> ...))`. `TicketTab` uses it in place of the sync worker; pause/stop via the shared `RunControl`.

- [ ] **Step 1: Write the failing test** — `tests/test_async_runner.py`:
```python
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop, QTimer
from scraper.async_runner import AsyncTicketWorker

def test_worker_emits_finished(tmp_path):
    app = QApplication.instance() or QApplication([])
    # crash-free fake: workers=1, 2 fake tickets via the test injection hook
    w = AsyncTicketWorker.for_test(["1", "2"], tmp_path)   # see impl note
    got = {}
    w.finished_report.connect(lambda rep: got.update(rep))
    loop = QEventLoop(); w.finished_report.connect(lambda *_: loop.quit())
    QTimer.singleShot(10_000, loop.quit)   # safety timeout
    w.start(); loop.exec()
    assert got.get("saved") == 2
```
- [ ] **Step 2: Run → fail** (`async_runner` missing).
- [ ] **Step 3: Implement** `scraper/async_runner.py` — a QThread whose `run()` builds signal-emitting `TicketEngineCallbacks` and calls `asyncio.run(run_ticket_scrape_async(...))`. Provide a `for_test(ids, out)` classmethod that injects the Task-3 fakes (FakeAsyncBrowser + fake portal + login_once + fake parse) so the GUI bridge is testable offscreen without a browser. Real construction wires `AsyncBrowser`, `tradedesk_portal_async.make_factory(base)`, `tradedesk_login_once`, and `mode="light"`.
  (Full code: signal class + callbacks adapter that calls `self.<signal>.emit(...)`; `run()` wraps `asyncio.run`; on exception emits `log("error", type(exc).__name__)`.)
- [ ] **Step 4: Wire `TicketTab`** to start `AsyncTicketWorker` (light mode) instead of the sync engine; keep the existing Workers spinbox (1–10), Pause/Resume/Stop via `RunControl`, output from `app_settings.tickets_dir()`, the 4-col table, and `shutdown()` (cancel + `wait()`).
- [ ] **Step 5: Run** `scraper\venv\Scripts\python.exe -m pytest tests/test_async_runner.py tests/test_ticket_tab.py -v` → pass. Offscreen launch check: `set QT_QPA_PLATFORM=offscreen && scraper\venv\Scripts\python.exe -c "from scraper.gui import MainWindow; from PySide6.QtWidgets import QApplication; a=QApplication([]); MainWindow(); print('gui-ok')"`.
- [ ] **Step 6: Commit** `git add scraper/async_runner.py scraper/ticket_tab.py tests/test_async_runner.py && git commit -m "feat(v4.0.1): GUI runs async light-mode engine via QThread+signals"`

---

### Task 6: LIVE reliability diagnosis + verification (controller + operator)

Interactive. Uses superpowers:systematic-debugging. The operator logs into portal.contoso.example in the headed window.

- [ ] **Step 1: Full suite green** `scraper\venv\Scripts\python.exe -m pytest tests/ -q`.
- [ ] **Step 2: Single-ticket live smoke** — operator logged in; run light mode (workers=1) on **76511** then **76091**. Confirm the canonical schema is fully populated: fields, comments, comment images, files, resolution text + resolution comments + resolution files. Capture any failure with diagnostics (log detected sub-view counts, page URL, selector waits) — do NOT guess fixes; trace root cause per systematic-debugging.
- [ ] **Step 3: Fix root causes** found live (condition-based waits, re-login on expiry, selector drift). One hypothesis at a time; re-verify after each. Log each fix to `.wolf/buglog.json`.
- [ ] **Step 4: Concurrency/light-load test** — run light mode at workers=4 then workers=10 on **71456–71467** (12 tickets). Confirm: machine does **not** freeze (one Chrome window), no ticket stranded at "queued", completeness holds. Note resource feel vs the old per-worker-Chrome model.
- [ ] **Step 5: Operator confirms** the new portal now scrapes reliably in light mode. Record results in the ledger.
- [ ] **Step 6: Final task review** (subagent, opus) of the Phase 1 diff (base = Phase-1 plan commit) — concurrency correctness of the async engine, no-PII-in-logs, schema conformance, GUI thread safety. Fix Critical/Important. Do NOT build the exe (that is Phase 4).

---

## Self-Review
- **Spec coverage:** async-unified core (T1-T3), light mode 1-browser/1-login/N-tabs (T2-T3), crash resilience ported (T3), async tradedesk adapter (T4), GUI light-mode via QThread (T5), live reliability fix + golden-ticket + 71456-71467 validation (T6). Multi-window deferred to Phase 2, old portal to Phase 3, packaging to Phase 4 — matches spec phasing. ✅
- **Placeholder scan:** T1-T4 carry full code; T5 gives the QThread/signal structure + a concrete test + the wiring checklist (the bridge is mechanical given T3's signature); T6 is an inherently interactive live procedure. The one prose-described piece (async_runner full body) is bounded by its test and signal list. ✅
- **Type consistency:** `run_ticket_scrape_async(...page_portal_factory, login_once, parse_fn, mode)` is used identically in T3 tests, T4 wiring note, and T5; `TicketEngineCallbacks` (5 callbacks) reused from sync engine; `empty_ticket`/canonical schema consistent T1↔T3↔T4; `MAX_TICKET_ATTEMPTS`/`MAX_WORKER_REBUILDS` imported from the sync module. ✅
- **Risk:** async Playwright API specifics (T2/T4) verified live in T6; if `browser.new_context` default-timeout or `expect_download` async form needs adjustment, fix during T6 and recommit. The sync `Browser`/KB engines are untouched.
