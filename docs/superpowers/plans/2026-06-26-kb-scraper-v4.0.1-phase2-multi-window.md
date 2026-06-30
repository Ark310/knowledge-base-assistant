# KB Scraper v4.0.1 — Phase 2: Multi-Window Mode + Settings Toggle — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add the **multi-window** browser mode (each worker = its own Chrome window + its own login) selectable via a **Settings toggle**, with the worker-count slider driving both modes. Light mode stays the default.

**Architecture:** The async engine already runs N worker coroutines off one `asyncio.Queue`. Phase 2 makes **browser provisioning** mode-aware: `light` keeps one shared browser + one login (a page/tab per worker); `multi` gives each worker its own `AsyncBrowser` + login (a separate window). All the crash-resilience (redispatch / rebuild / drain / exactly-once / awaitable pause) is unchanged — only how a worker acquires its page differs, and in `multi` a crash rebuilds the whole browser. The mode is persisted in `app_settings` and read by `ticket_tab`.

**Tech Stack:** asyncio + async Playwright, PySide6, pytest. Test interpreter `scraper\venv\Scripts\python.exe`. Builds on Phase 1 (branch `feat/kb-scraper-v4.0.1`, head `da17a56`).

## Global Constraints
- Password → OS keyring only; never on disk, never logged, never in process args.
- No PII/secrets in logs — exception **type** only.
- System Chrome via `channel="chrome"`; no bundled browser.
- Light mode stays the **default**; `multi` is opt-in via Settings.
- Worker-count (1–10) drives BOTH modes (tabs in light, windows in multi).
- Do NOT change the sync engine, KB engines, or the parsers.

---

### Task 1: Persist the browser mode in app_settings

**Files:** Modify `scraper/app_settings.py`; Test `tests/test_app_settings.py` (add cases).

**Interfaces:**
- Produces: `browser_mode() -> str` (returns `"light"` | `"multi"`, default `"light"`), `set_browser_mode(mode: str) -> None` (merges into the settings file, never clobbering tickets_dir/kb_dir). `save(...)` must also merge so it never wipes `browser_mode`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_app_settings.py`:
```python
def test_browser_mode_default_is_light(tmp_path, monkeypatch):
    import scraper.app_settings as s
    monkeypatch.setattr(s, "_file", lambda: tmp_path / "app_settings.json")
    assert s.browser_mode() == "light"

def test_set_browser_mode_persists_and_preserves_paths(tmp_path, monkeypatch):
    import scraper.app_settings as s
    monkeypatch.setattr(s, "_file", lambda: tmp_path / "app_settings.json")
    s.save("T:/tickets", "K:/kb")
    s.set_browser_mode("multi")
    assert s.browser_mode() == "multi"
    # set_browser_mode must NOT wipe the saved paths
    assert str(s.tickets_dir()) in ("T:\\tickets", "T:/tickets")
    assert str(s.kb_dir()) in ("K:\\kb", "K:/kb")

def test_invalid_browser_mode_falls_back_to_light(tmp_path, monkeypatch):
    import scraper.app_settings as s
    monkeypatch.setattr(s, "_file", lambda: tmp_path / "app_settings.json")
    s.set_browser_mode("bogus")
    assert s.browser_mode() == "light"
```
- [ ] **Step 2: Run → fail** `scraper\venv\Scripts\python.exe -m pytest tests/test_app_settings.py -v` (browser_mode/set_browser_mode undefined).
- [ ] **Step 3: Implement** in `scraper/app_settings.py`. Make `save()` merge, and add the two functions:
```python
_VALID_MODES = ("light", "multi")

def save(tickets_dir: str, kb_dir: str, browser_mode: str | None = None) -> None:
    d = load()
    d["tickets_dir"] = str(tickets_dir)
    d["kb_dir"] = str(kb_dir)
    if browser_mode in _VALID_MODES:
        d["browser_mode"] = browser_mode
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")

def browser_mode() -> str:
    m = load().get("browser_mode")
    return m if m in _VALID_MODES else "light"

def set_browser_mode(mode: str) -> None:
    d = load()
    d["browser_mode"] = mode if mode in _VALID_MODES else "light"
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")
```
  (Replace the existing `save()` with the merging version above.)
- [ ] **Step 4: Run → pass** the three new tests + the full `tests/test_app_settings.py`.
- [ ] **Step 5: Commit** `git add scraper/app_settings.py tests/test_app_settings.py && git commit -m "feat(v4.0.1): persist browser_mode (light|multi) in app_settings (merging save)"`

---

### Task 2: Multi-window provisioning in the async engine

**Files:** Modify `scraper/ticket_engine_async.py`; Test `tests/test_ticket_engine_async.py` (add cases).

**Interfaces:**
- Consumes: existing `run_ticket_scrape_async(..., browser_factory, page_portal_factory, login_once, parse_fn, mode)`. `mode` is already a param; this task makes `mode="multi"` real.
- Produces: same signature/behavior; in `multi`, each worker opens its own browser via `browser_factory()` + `login_once`, and rebuilds the whole browser on crash. In `light`, unchanged (one shared browser + login, page-per-worker).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_ticket_engine_async.py`:
```python
def test_multi_mode_own_browser_and_login_per_worker(tmp_path):
    created = {"n": 0}
    def bf():
        created["n"] += 1
        return FakeAsyncBrowser()
    logins = {"n": 0}
    async def login_once(browser, u, p):
        logins["n"] += 1; return True
    factory, _ = make_factory(lambda tid, n: False)
    def fake_parse(html, tid, base):
        return {**empty_ticket(tid, base), "title": tid}
    rec = {}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ["1", "2", "3", "4"], force=True, control=RunControl(), cb=_cb(rec),
        workers=2, output_dir=tmp_path, browser_factory=bf,
        page_portal_factory=factory, login_once=login_once, parse_fn=fake_parse, mode="multi"))
    assert all(s == "ok" for _, s in rec["tickets"]) and rec["report"]["saved"] == 4
    # multi: one browser + one login PER WORKER (n_workers = min(2,4) = 2), not a single shared one
    assert created["n"] >= 2 and logins["n"] >= 2

def test_multi_mode_login_failure_drains_all_failed(tmp_path):
    async def login_fail(browser, u, p): return False
    factory, _ = make_factory(lambda tid, n: False)
    def fake_parse(html, tid, base):
        return {**empty_ticket(tid, base), "title": tid}
    rec = {}
    asyncio.run(tea.run_ticket_scrape_async(
        "https://x", "u", "p", ["1", "2"], force=True, control=RunControl(), cb=_cb(rec),
        workers=2, output_dir=tmp_path, browser_factory=lambda: FakeAsyncBrowser(),
        page_portal_factory=factory, login_once=login_fail, parse_fn=fake_parse, mode="multi"))
    assert all(s == "failed" for _, s in rec["tickets"]) and rec["report"]["failed"] == 2
```
- [ ] **Step 2: Run → fail** (today `mode="multi"` still uses the shared browser, so `created["n"]` is 1 and the assertions fail).
- [ ] **Step 3: Implement.** Replace the block in `run_ticket_scrape_async` that currently starts at `browser = await browser_factory().open()` and runs to the end (`return stats`) with this mode-aware version (everything ABOVE it — queue/attempts/finished/lock/terminal — is unchanged):
```python
    # ── Browser provisioning differs by mode ─────────────────────────────────
    # light : ONE shared browser + ONE login; each worker opens a tab (page).
    # multi : each worker opens its OWN browser + logs in (separate windows).
    shared_browser = None
    if mode != "multi":
        shared_browser = await browser_factory().open()
        if not await login_once(shared_browser, username, password):
            cb.on_log("error", "Login failed; aborting.")
            while not pending.empty():
                await terminal(pending.get_nowait(), "failed", "failed")
            await shared_browser.close()
            cb.on_finished(stats)
            return stats

    async def _open_worker_page():
        """Acquire (own_browser_or_None, page) for a worker per mode. Raises on failure."""
        if mode == "multi":
            b = await browser_factory().open()
            if not await login_once(b, username, password):
                await b.close()
                raise RuntimeError("login failed")
            return b, await b.new_page()
        return None, await shared_browser.new_page()

    async def worker(idx):
        prefix = f"[W{idx + 1}] " if workers > 1 else ""
        if control.cancelled:
            return
        own_browser = None
        page = None
        rebuilds = 0
        try:
            try:
                own_browser, page = await _open_worker_page()
            except Exception:
                cb.on_log("error", f"{prefix}could not start (browser/login) — worker exiting.")
                return
            portal = page_portal_factory(page)
            while True:
                await control.wait_if_paused_async()
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
                        cb.on_log("warning", f"{prefix}#{tid}: session expired")
                        raise RuntimeError("session expired")
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
                    # tear down this worker's page (+ its own browser in multi mode)
                    try:
                        if page is not None:
                            await page.close()
                    except Exception:
                        pass
                    if own_browser is not None:
                        try:
                            await own_browser.close()
                        except Exception:
                            pass
                        own_browser = None
                    page = None
                    if rebuilds > MAX_WORKER_REBUILDS:
                        cb.on_log("error", f"{prefix}too many crashes — worker exiting.")
                        break
                    try:
                        own_browser, page = await _open_worker_page()
                        portal = page_portal_factory(page)
                    except Exception:
                        cb.on_log("error", f"{prefix}rebuild failed — worker exiting.")
                        page = None
                        break
        finally:
            try:
                if page is not None:
                    await page.close()
            except Exception:
                pass
            if own_browser is not None:
                try:
                    await own_browser.close()
                except Exception:
                    pass

    cb.on_log("info",
        f"--- Starting ticket scrape: {total} tickets"
        + (f" ({workers} workers, {mode})" if workers > 1 else "") + " ---")
    try:
        if total:
            n_workers = max(1, min(workers, total))
            await asyncio.gather(*(worker(i) for i in range(n_workers)))
            if not control.cancelled:
                while not pending.empty():
                    tid = pending.get_nowait()
                    cb.on_log("error",
                        f"#{tid}: not processed (all workers stopped) — marked failed.")
                    await terminal(tid, "failed", "failed")
        async with lock:
            stats["retried"] = sum(1 for c in attempts.values() if c > 1)
        if total and stats["failed"] == total:
            cb.on_log("error",
                f"All {total} tickets failed — check credentials/network/portal.")
    finally:
        if shared_browser is not None:
            await shared_browser.close()
    cb.on_finished(stats)
    return stats
```
- [ ] **Step 4: Run → pass** `scraper\venv\Scripts\python.exe -m pytest tests/test_ticket_engine_async.py -v` (all light-mode tests STILL pass + the 2 new multi tests).
- [ ] **Step 5: Flakiness** — run the file 5× (PowerShell `1..5 | % { ... }`); all pass each run.
- [ ] **Step 6: Full suite** `scraper\venv\Scripts\python.exe -m pytest tests/ -q` (expect 199 + 2 = 201).
- [ ] **Step 7: Commit** `git add scraper/ticket_engine_async.py tests/test_ticket_engine_async.py && git commit -m "feat(v4.0.1): multi-window engine mode — own browser+login per worker (light unchanged)"`

---

### Task 3: Settings toggle + ticket_tab wiring

**Files:** Modify `scraper/settings_dialog.py` (add the Browser-mode control), `scraper/ticket_tab.py` (pass the mode); Test `tests/test_settings_dialog.py` + `tests/test_ticket_tab.py` (add cases). READ all three files first.

**Interfaces:**
- Consumes: `app_settings.browser_mode()` / `set_browser_mode()` (Task 1); `AsyncTicketWorker(..., mode=...)` (exists).
- Produces: a Settings control (two radio buttons or a combo: **"Light — one window, many tabs (recommended)"** / **"Multi-window — one Chrome per worker"**) persisted via app_settings; `TicketTab._start` constructs `AsyncTicketWorker(..., mode=app_settings.browser_mode())`.

- [ ] **Step 1: Write the failing tests.**
  - `tests/test_settings_dialog.py` (append) — the dialog reflects + persists the mode (offscreen; follow the file's existing QApplication/offscreen pattern):
```python
def test_settings_dialog_persists_browser_mode(tmp_path, monkeypatch):
    import os; os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import scraper.app_settings as s
    monkeypatch.setattr(s, "_file", lambda: tmp_path / "app_settings.json")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from scraper.settings_dialog import SettingsDialog
    dlg = SettingsDialog()
    dlg.set_browser_mode_value("multi")   # helper the dialog exposes for the control
    dlg._save()                            # the dialog's save handler
    assert s.browser_mode() == "multi"
```
  - `tests/test_ticket_tab.py` (append) — `_start` passes the persisted mode to the worker (monkeypatch the worker class to capture kwargs, don't launch a real scrape):
```python
def test_ticket_tab_passes_browser_mode_to_worker(tmp_path, monkeypatch):
    import os; os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import scraper.app_settings as s
    monkeypatch.setattr(s, "_file", lambda: tmp_path / "app_settings.json")
    s.set_browser_mode("multi")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import scraper.ticket_tab as tt
    captured = {}
    class _StubWorker:
        def __init__(self, *a, **k): captured.update(k); self.control = k.get("control")
        def __getattr__(self, n): return lambda *a, **k: None   # signals/.start/.connect no-op
    monkeypatch.setattr(tt, "AsyncTicketWorker", _StubWorker)
    tab = tt.TicketTab()
    # provide credentials + ids so _start proceeds (stub ticket_settings.load_password)
    import scraper.ticket_settings as ts
    monkeypatch.setattr(ts, "load", lambda: {"portal_url": "https://x", "username": "u"})
    monkeypatch.setattr(ts, "load_password", lambda u: "pw")
    tab.txt_tickets.setPlainText("76511")   # adjust to the real input widget name when reading the file
    tab._start()
    assert captured.get("mode") == "multi"
```
  NOTE for implementer: read `ticket_tab.py` to use the REAL input-widget attribute name and `_start` preconditions; adjust the test to match (keep the assertion `captured["mode"] == "multi"`). If `_start` shows a modal on missing input, set whatever the real fields are.
- [ ] **Step 2: Run → fail** (no Browser-mode control / mode not passed).
- [ ] **Step 3: Implement.**
  - `settings_dialog.py`: add a Browser-mode group (2 QRadioButtons, default from `app_settings.browser_mode()`), a `set_browser_mode_value(m)` setter + a getter, and in the existing save handler call `app_settings.set_browser_mode(<selected>)` (or pass to `save(...)`). Keep the existing output-folder + credentials sections untouched.
  - `ticket_tab.py`: in `_start`, read `mode = app_settings.browser_mode()` and pass `mode=mode` to `AsyncTicketWorker(...)`.
- [ ] **Step 4: Run → pass** the two new tests + `tests/test_settings_dialog.py tests/test_ticket_tab.py`.
- [ ] **Step 5: Offscreen GUI construct** `$env:QT_QPA_PLATFORM='offscreen'; scraper\venv\Scripts\python.exe -c "from scraper.gui import MainWindow; from PySide6.QtWidgets import QApplication; a=QApplication([]); MainWindow(); print('gui-ok')"`.
- [ ] **Step 6: Full suite** (expect 201 + 2 = 203).
- [ ] **Step 7: Commit** `git add scraper/settings_dialog.py scraper/ticket_tab.py tests/test_settings_dialog.py tests/test_ticket_tab.py && git commit -m "feat(v4.0.1): Settings browser-mode toggle wired into the Tickets tab"`

---

### Task 4: Gate + final review

- [ ] **Step 1: Full suite green** (203).
- [ ] **Step 2: Final review** (subagent, opus) of the Phase-2 diff (base = Phase-1 head `da17a56`): correctness of the multi-mode provisioning (browser/page lifecycle, no leaks on rebuild/exit, exactly-once still holds), settings merge (no path clobber), GUI wiring, security/policy, test quality. Fix Critical/Important.
- [ ] **Step 3: Operator live check (optional, recommended):** flip the Settings toggle to Multi-window, scrape a few tickets, confirm N separate Chrome windows open + complete; flip back to Light. (Controller can drive via keyring creds with `mode="multi"` if the operator prefers.)
- [ ] **Step 4:** Update ledger + memory; mark Phase 2 complete. No exe build (Phase 4).

---

## Self-Review
- **Spec coverage:** browser-mode persisted (T1), multi-window engine = own browser+login per worker (T2), Settings toggle + worker-count drives both (T3), gate/review (T4). Matches spec §"Two worker modes". ✅
- **Placeholder scan:** T1/T2 carry full code; T3 carries full test + control spec and flags the two file-specific names (input widget, save handler) for the implementer to bind on read — bounded, not open-ended. ✅
- **Type consistency:** `mode` param threaded app_settings.browser_mode() → ticket_tab → AsyncTicketWorker(mode=) → run_ticket_scrape_async(mode=); `browser_mode()`/`set_browser_mode()` consistent T1↔T3; FakeAsyncBrowser reused from the Phase-1 test file. ✅
- **Risk:** multi mode is intentionally heavier (the original resource cost) — it is opt-in; light stays default. Browser/page lifecycle in multi verified by tests + the opus review + optional live check.
