# KB Scraper v4.0.4 "KB Parity + Finalize" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the Knowledge Base tab to ticket-tab parity — parallel async scraping with auto-recovery and per-article timeouts, three-layer completeness assurance (post-run audit, retry-failures, full library audit), and the tab UI kit (workers/priority/monitor/buffered log/alerts) — then version 4.0.4 and the gated build.

**Architecture:** New `scraper/kb_engine_async.py` mirrors the battle-tested `scraper/ticket_engine_async.py` (BrowserSupervisor, AdaptiveGate + tuner, shared queue, bounded redispatch, park/unpark, pause+alert-never-mass-fail), swapping the per-item pipeline for the KB article steps (navigate → expand macros → screenshot → parse → save) wrapped in a hard `asyncio.wait_for` timeout. Completeness lives in a pure `scraper/kb_audit.py`. The KB tab reuses the ticket tab's widgets (new shared `LogPane`, existing `ResourceMonitorWidget`, priority pattern). Release Notes keeps its old sync engine.

**Tech Stack:** Python 3.11, Playwright async, PySide6, psutil, pytest. Spec: `docs/superpowers/specs/2026-07-07-kb-scraper-v4.0.4-kb-parity-design.md`.

## Global Constraints

- Log exception TYPES only, never messages (org policy — no PII/secrets in logs). Alert bodies: static text + counts only.
- Branch: `feat/kb-scraper-v4.0.3` (continues; APP_VERSION becomes `4.0.4`). Suite baseline: **315 green** — keep green every commit; target ≥ 345.
- Run tests: `scraper\venv\Scripts\python.exe -m pytest tests\ -q` from repo root.
- **bug-149 rule:** every NEW test file that drives a scrape engine gets its own autouse state-isolation fixture (monkeypatch the engine's state seam to tmp_path). Verify the real `scraper/state/` files are untouched by suite runs.
- Worker hard cap 10. Light mode only for KB (no multi mode — Confluence needs no login).
- KB pipeline pieces reused UNCHANGED: `discover_articles`, `parse_article`, `save_article`, `generate_kb_index`. RN engine (`scraper/engine.py` Engine) untouched.
- Build: fresh `--workpath build_v404`, one-folder, `--distpath dist`. NO exe build before operator-confirmed live smoke (standing rule).
- The existing legacy KB state file (`state/scraped_articles.json`) is read-only for migration — never rewritten or deleted.

---

### Task 1: Completeness audit module (`scraper/kb_audit.py`)

**Files:**
- Create: `scraper/kb_audit.py`
- Test: `tests/test_kb_audit.py`

**Interfaces:**
- Consumes: `scraper.kb_discovery.discover_articles(space_key)` (returns `[{title, url, page_id, slug}]`); article files live at `output_base / cfg["product"] / cfg["lib_folder"] / f"{slug}.json"` (same slug the discovery dict carries — `kb_discovery._slugify` and `article_writer.safe_slug` are the same transform).
- Produces: `audit_spaces(space_cfgs: list[dict], output_base: Path, discover=None) -> dict` returning
  `{"spaces": {space_key: {"display_name", "discovered": int, "on_disk": int, "missing": [article...], "error": str|None}}, "totals": {"discovered", "on_disk", "missing", "spaces_with_errors"}}` where each `missing` entry is the discovery dict (title/url/slug) PLUS `"space_key"`. `discover=None` uses the real `discover_articles`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_kb_audit.py
"""kb_audit — discovered-vs-on-disk verification. Pure; discovery injected."""
import json
from pathlib import Path

from scraper.kb_audit import audit_spaces

CFG_A = {"space_key": "SA", "display_name": "SysAdmin", "product": "tradedesk", "lib_folder": "system_administration"}
CFG_B = {"space_key": "howto", "display_name": "How To's", "product": "web2", "lib_folder": "how_to"}


def _art(title, slug):
    return {"title": title, "url": f"https://kb/x/{slug}", "page_id": "1", "slug": slug}


def _write(base: Path, cfg, slug):
    d = base / cfg["product"] / cfg["lib_folder"]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.json").write_text(json.dumps({"title": slug}), encoding="utf-8")


def test_audit_flags_missing_articles(tmp_path):
    def discover(key):
        return [_art("On Disk", "on_disk"), _art("Lost One", "lost_one")]
    _write(tmp_path, CFG_A, "on_disk")
    res = audit_spaces([CFG_A], tmp_path, discover=discover)
    sa = res["spaces"]["SA"]
    assert (sa["discovered"], sa["on_disk"]) == (2, 1)
    assert [m["slug"] for m in sa["missing"]] == ["lost_one"]
    assert sa["missing"][0]["space_key"] == "SA"
    assert res["totals"] == {"discovered": 2, "on_disk": 1, "missing": 1, "spaces_with_errors": 0}


def test_audit_clean_space_has_no_missing(tmp_path):
    def discover(key):
        return [_art("A", "a")]
    _write(tmp_path, CFG_A, "a")
    res = audit_spaces([CFG_A], tmp_path, discover=discover)
    assert res["spaces"]["SA"]["missing"] == []
    assert res["totals"]["missing"] == 0


def test_audit_survives_discovery_failure_and_marks_error(tmp_path):
    def discover(key):
        if key == "SA":
            raise RuntimeError("confluence down")
        return [_art("B", "b")]
    _write(tmp_path, CFG_B, "b")
    res = audit_spaces([CFG_A, CFG_B], tmp_path, discover=discover)
    assert res["spaces"]["SA"]["error"] == "RuntimeError"       # TYPE only, no message
    assert res["spaces"]["howto"]["error"] is None
    assert res["totals"]["spaces_with_errors"] == 1


def test_audit_empty_space_is_clean_not_error(tmp_path):
    res = audit_spaces([CFG_A], tmp_path, discover=lambda key: [])
    assert res["spaces"]["SA"] == {"display_name": "SysAdmin", "discovered": 0,
                                   "on_disk": 0, "missing": [], "error": None}
```

- [ ] **Step 2: Run to verify failure**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_kb_audit.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.kb_audit'`

- [ ] **Step 3: Implement `scraper/kb_audit.py`**

```python
"""Completeness audit for the KB library (v4.0.4, R3).

Compares live discovery against the JSON files actually on disk, per space.
Pure and injectable: discovery failures never raise — they mark the space with
the exception TYPE (org policy: no messages in reports/logs).
"""
from __future__ import annotations
from pathlib import Path


def audit_spaces(space_cfgs: list[dict], output_base: Path, discover=None) -> dict:
    if discover is None:
        from scraper.kb_discovery import discover_articles as discover
    output_base = Path(output_base)
    spaces: dict = {}
    totals = {"discovered": 0, "on_disk": 0, "missing": 0, "spaces_with_errors": 0}
    for cfg in space_cfgs:
        key = cfg["space_key"]
        entry = {"display_name": cfg["display_name"], "discovered": 0,
                 "on_disk": 0, "missing": [], "error": None}
        try:
            articles = discover(key)
        except Exception as exc:
            entry["error"] = type(exc).__name__
            totals["spaces_with_errors"] += 1
            spaces[key] = entry
            continue
        art_dir = output_base / cfg["product"] / cfg["lib_folder"]
        entry["discovered"] = len(articles)
        for art in articles:
            if (art_dir / f"{art['slug']}.json").exists():
                entry["on_disk"] += 1
            else:
                entry["missing"].append({**art, "space_key": key})
        totals["discovered"] += entry["discovered"]
        totals["on_disk"] += entry["on_disk"]
        totals["missing"] += len(entry["missing"])
        spaces[key] = entry
    return {"spaces": spaces, "totals": totals}
```

- [ ] **Step 4: Run tests, full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_kb_audit.py -q` (4 passed), then full suite (319).

```bash
git add scraper/kb_audit.py tests/test_kb_audit.py
git commit -m "feat(v4.0.4): kb_audit — discovered-vs-on-disk completeness audit"
```

---

### Task 2: Journaled KB scraped-state + legacy migration (`scraper/kb_state.py`)

**Files:**
- Create: `scraper/kb_state.py`
- Test: `tests/test_kb_state.py`

**Interfaces:**
- Consumes: `scraper.scrape_state.ScrapedState` (Task 4 of v4.0.3 — `ScrapedState(state_file, every=25, interval=10.0)`, `.load() -> set[str]`, `.mark(key)`, `.flush()`); legacy file `scraper.kb_config.KB_ARTICLES_STATE_FILE` with shape `{space_key: {slug: {"url", "scraped_at"}}}` (written by `core.StateTracker`).
- Produces: `KB_STATE_V2_FILE` (default `STATE_DIR / "scraped_articles_v2.json"`); `kb_key(space_key: str, slug: str) -> str` (returns `f"{space_key}|{slug}"`); `load_kb_state(state_file=None, legacy_file=None) -> ScrapedState` — creates the ScrapedState, `.load()`s it, and if the loaded set is EMPTY and the legacy file exists, seeds it from legacy (mark every space|slug, flush once) without touching the legacy file.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_kb_state.py
"""kb_state — journaled KB scraped-state + one-time legacy migration."""
import json

from scraper.kb_state import kb_key, load_kb_state


def test_kb_key_format():
    assert kb_key("SA", "some_article") == "SA|some_article"


def test_fresh_state_no_legacy(tmp_path):
    st = load_kb_state(state_file=tmp_path / "v2.json", legacy_file=tmp_path / "legacy.json")
    assert st.ids == set()
    st.mark(kb_key("SA", "a")); st.flush()
    assert set(json.loads((tmp_path / "v2.json").read_text())) == {"SA|a"}


def test_migrates_legacy_once_and_leaves_legacy_untouched(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({
        "SA": {"a1": {"url": "u", "scraped_at": "t"}, "a2": {"url": "u", "scraped_at": "t"}},
        "howto": {"b1": {"url": "u", "scraped_at": "t"}},
    }))
    before = legacy.read_text()
    st = load_kb_state(state_file=tmp_path / "v2.json", legacy_file=legacy)
    assert st.ids == {"SA|a1", "SA|a2", "howto|b1"}
    assert legacy.read_text() == before                      # read-only migration
    # migrated ids are persisted (survive a reload without legacy re-read)
    st2 = load_kb_state(state_file=tmp_path / "v2.json", legacy_file=tmp_path / "gone.json")
    assert st2.ids == {"SA|a1", "SA|a2", "howto|b1"}


def test_existing_v2_state_skips_migration(tmp_path):
    (tmp_path / "v2.json").write_text(json.dumps(["SA|kept"]))
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"SA": {"ignored": {"url": "u", "scraped_at": "t"}}}))
    st = load_kb_state(state_file=tmp_path / "v2.json", legacy_file=legacy)
    assert st.ids == {"SA|kept"}                             # no merge once v2 exists


def test_corrupt_legacy_degrades_to_empty(tmp_path):
    legacy = tmp_path / "legacy.json"
    legacy.write_text("{not json")
    st = load_kb_state(state_file=tmp_path / "v2.json", legacy_file=legacy)
    assert st.ids == set()
```

- [ ] **Step 2: Run to verify failure**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_kb_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scraper.kb_state'`

- [ ] **Step 3: Implement `scraper/kb_state.py`**

```python
"""Journaled KB article scraped-state (v4.0.4).

The legacy sync engine rewrote state/scraped_articles.json per article via
core.StateTracker. The async KB engine uses the ticket engine's ScrapedState
(journal + batched compaction) with keys "{space_key}|{slug}" in a NEW v2
file. One-time migration seeds v2 from the legacy dict so nothing re-scrapes;
the legacy file is never modified (the RN/sync paths still own it).
"""
from __future__ import annotations
import json
from pathlib import Path

from scraper.scrape_state import ScrapedState


def _default_files():
    from scraper.kb_config import KB_ARTICLES_STATE_FILE
    from scraper.config import STATE_DIR
    return Path(STATE_DIR) / "scraped_articles_v2.json", Path(KB_ARTICLES_STATE_FILE)


def kb_key(space_key: str, slug: str) -> str:
    return f"{space_key}|{slug}"


def load_kb_state(state_file: Path | None = None, legacy_file: Path | None = None) -> ScrapedState:
    default_v2, default_legacy = _default_files()
    state_file = Path(state_file) if state_file else default_v2
    legacy_file = Path(legacy_file) if legacy_file else default_legacy
    st = ScrapedState(state_file=state_file)
    st.load()
    if not st.ids and legacy_file.exists():
        try:
            legacy = json.loads(legacy_file.read_text(encoding="utf-8"))
            for space_key, slugs in (legacy or {}).items():
                for slug in (slugs or {}):
                    st.mark(kb_key(space_key, slug))
            st.flush()
        except Exception:
            pass    # corrupt legacy: start empty; legacy file is left as-is
    return st
```

- [ ] **Step 4: Run tests, full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_kb_state.py -q` (5 passed), then full suite (324).

```bash
git add scraper/kb_state.py tests/test_kb_state.py
git commit -m "feat(v4.0.4): journaled KB scraped-state + read-only legacy migration"
```

---

### Task 3: Async article page-ops (`scraper/kb_page_ops.py`)

**Files:**
- Create: `scraper/kb_page_ops.py`
- Test: `tests/test_kb_page_ops.py`

**Interfaces:**
- Consumes: a Playwright async `page` (duck-typed in tests).
- Produces: `async expand_macros(page) -> None` and `async capture_article(page, url: str, screenshot_path: Path) -> str` (navigates, expands, screenshots, returns HTML). These are async ports of `core.Browser.navigate/expand_confluence_macros/screenshot/get_content` — same selectors, same `domcontentloaded` + settle rationale.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_kb_page_ops.py
"""Async ports of the sync Confluence page ops. Fake page; asserts call shape."""
import asyncio
from pathlib import Path

from scraper.kb_page_ops import capture_article, expand_macros

class _FakeLocator:
    def __init__(self, buttons): self._buttons = buttons
    async def all(self): return self._buttons

class _FakeButton:
    def __init__(self, fail=False): self.fail = fail; self.clicks = 0
    async def click(self, timeout=None):
        self.clicks += 1
        if self.fail: raise RuntimeError("not clickable")

class _FakePage:
    def __init__(self):
        self.gotos, self.shots, self.waits = [], [], 0
        self.buttons = [_FakeButton(), _FakeButton(fail=True)]
    async def goto(self, url, wait_until=None, timeout=None):
        self.gotos.append((url, wait_until))
    async def wait_for_timeout(self, ms): self.waits += 1
    def locator(self, sel): return _FakeLocator(self.buttons)
    async def screenshot(self, path=None, full_page=None): self.shots.append((path, full_page))
    async def content(self): return "<html>ok</html>"


def test_expand_macros_clicks_all_and_swallows_failures():
    page = _FakePage()
    asyncio.run(expand_macros(page))
    assert all(b.clicks >= 1 for b in page.buttons)       # failing button didn't abort


def test_capture_article_full_pipeline(tmp_path):
    page = _FakePage()
    html = asyncio.run(capture_article(page, "https://kb/x", tmp_path / "s" / "a.png"))
    assert html == "<html>ok</html>"
    assert page.gotos[0] == ("https://kb/x", "domcontentloaded")
    assert page.shots[0][1] is True                        # full_page screenshot
    assert (tmp_path / "s").exists()                       # parent dir created
```

- [ ] **Step 2: Run to verify failure**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_kb_page_ops.py -q`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `scraper/kb_page_ops.py`**

```python
"""Async Confluence article page ops (v4.0.4) — ports of core.Browser's sync
navigate/expand_confluence_macros/screenshot/get_content. Selectors and the
domcontentloaded rationale are identical (Confluence background WebSocket
polling means networkidle never fires). No retries here — the engine's
attempt/redispatch machinery owns retry policy."""
from __future__ import annotations
from pathlib import Path

_EXPAND_SELECTORS = [
    ".expand-control",
    "[data-macro-name='expand'] .expand-control-text",
    ".aui-expander-trigger",
    "a.expand-control",
]


async def expand_macros(page) -> None:
    for selector in _EXPAND_SELECTORS:
        try:
            for btn in await page.locator(selector).all():
                try:
                    await btn.click(timeout=1_000)
                    await page.wait_for_timeout(150)
                except Exception:
                    pass
        except Exception:
            pass


async def capture_article(page, url: str, screenshot_path: Path) -> str:
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(1_500)
    await expand_macros(page)
    screenshot_path = Path(screenshot_path)
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(screenshot_path), full_page=True)
    return await page.content()
```

- [ ] **Step 4: Run tests, full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_kb_page_ops.py -q` (2 passed), then full suite (326).

```bash
git add scraper/kb_page_ops.py tests/test_kb_page_ops.py
git commit -m "feat(v4.0.4): async Confluence page ops (navigate/expand/screenshot)"
```

---

### Task 4: Async KB engine (`scraper/kb_engine_async.py`) + `EngineCallbacks.on_alert`

**Files:**
- Modify: `scraper/engine.py:21-27` (add `on_alert` to EngineCallbacks)
- Create: `scraper/kb_engine_async.py`
- Test: `tests/test_kb_engine_async.py`

**Interfaces:**
- Consumes: `BrowserSupervisor` (scraper/supervisor.py — `start()`, `new_page()`, `recover(gen, reason)`, `reset_give_up()`, `give_up`, `generation`, `close()`; constructor `(browser_factory, login_once, username, password, cb, max_consecutive=3)` where `cb` needs `.on_log` and `.on_alert`); `AdaptiveGate` (+`tune`/`set_ceiling`); `RunControl` (`wait_if_paused_async`, `cancelled`, `target_workers`); `load_kb_state`/`kb_key` (Task 2); `audit_spaces` (Task 1); `capture_article` (Task 3); `parse_article`, `save_article`, `generate_kb_index`, `discover_articles`, `KB_SPACES` — all existing.
- Produces:

```python
ARTICLE_TIMEOUT_S = 90
MAX_ARTICLE_ATTEMPTS = 3
KB_REPORT_FILE  # same path as kb_engine.KB_REPORT_FILE (import it)

async def run_kb_scrape_async(
    space_cfgs: list[dict], *,                 # scope; ignored when items given
    force=False, control, cb=None,             # cb: EngineCallbacks (with on_alert)
    workers=4, output_base=None,               # default kb_config.KB_LIBRARY_BASE
    browser_factory,                           # () -> AsyncBrowser-like
    sampler=None, items=None,                  # items: explicit [(space_cfg, article)] (retry path)
    discover=None,                             # None -> discover_articles
    state=None,                                # None -> load_kb_state() (test seam)
    run_audit=True,
) -> dict
```

  Returns the report dict: `{"spaces": {key: {"discovered","new","skipped","failed","failed_urls":[...]}}, "failed_articles": [{space_key,title,url,slug,error_type}], "audit": <audit_spaces result or None>, "totals": {...}}`. Engine emits the existing callback surface per space (`on_status` after every article, `on_progress(space_key, title, done_overall, total_overall)`), plus `on_alert` for: give-up (from supervisor), breaker pause, cancel is silent, and the post-run audit summary (see Step 5).
- `EngineCallbacks.on_alert(self, severity, title, body) -> None: pass` added (no-op default — RN/sync paths unaffected).

- [ ] **Step 1: Add `on_alert` to `EngineCallbacks`** (in scraper/engine.py, after `on_finished`):

```python
    def on_alert(self, severity: str, title: str, body: str) -> None: pass
```

- [ ] **Step 2: READ `scraper/ticket_engine_async.py` end-to-end first.** The KB engine mirrors its worker-loop skeleton exactly: shared `asyncio.Queue`, `attempts`/`finished` dicts under an `asyncio.Lock`, `terminal()` exactly-once accounting, `_recover_page()` single-flight recovery loop with generation captured BEFORE the attempt, parking (`control.target_workers`, exit when queue empty or active slots dead), `_tuner` task (2s, `set_ceiling` + `sampler`→`tune`), breaker `consume_trip()` → pause + alert, drain only on cancel-leftovers. Copy those behaviors structurally; the differences are listed in Step 3.

- [ ] **Step 3: Write failing engine tests, then implement.** Test fixtures: build fakes in `tests/test_kb_engine_async.py` mirroring `tests/test_ticket_engine_async.py`'s style (fake AsyncBrowser whose `new_page()` returns fake pages; the engine must accept a `page_ops` injection OR the fake page must satisfy `capture_article` — simplest: give the fake page working `goto/wait_for_timeout/locator/screenshot/content` like Task 3's `_FakePage`, and monkeypatch `parse_article`/`save_article` inside the engine module to lightweight fakes recording calls). **Autouse isolation fixture required (bug-149):** monkeypatch `kb_engine_async.load_kb_state` to a tmp_path-backed loader in this test file.

Required tests (write all as real code against your fixtures):

```python
def test_parallel_scrape_all_articles_saved():
    """2 spaces × 4 articles, workers=3 → report: every article new, per-space
    stats correct, saved via save_article fake, state marked with kb_key."""

def test_skip_already_scraped_unless_force():
    """Seed state with one kb_key → skipped=1; force=True → new again."""

def test_frozen_article_times_out_and_is_bounded():
    """One article's page.content() hangs forever (asyncio.Event never set) with
    ARTICLE_TIMEOUT_S monkeypatched to 0.2 → TimeoutError → redispatched up to
    MAX_ARTICLE_ATTEMPTS then failed; run completes; failed_articles carries
    {error_type: 'TimeoutError'}; other articles all saved. (THE frozen-Chrome
    regression — the operator's lost-article bug.)"""

def test_browser_death_recovers_never_mass_fails():
    """browser_factory's first browser dies after N pages; supervisor recovery
    (mirroring the ticket test) → run completes, failed == 0."""

def test_discovery_failure_marks_space_and_continues():
    """discover raises for space A, returns 3 for space B → B fully scraped,
    report['spaces']['A'] has discovered=0 and an on_log error; no crash."""

def test_explicit_items_mode_scrapes_only_those():
    """items=[(cfg, art1), (cfg2, art7)] → exactly those scraped; discovery
    never called (pass discover=raiser)."""

def test_post_run_audit_alert_fires():
    """run_audit=True with an injected audit result containing missing>0 →
    cb.on_alert called once with 'warning'; missing==0+failed==0 → 'info'
    completeness-confirmed alert. (Inject via monkeypatching
    kb_engine_async.audit_spaces.)"""

def test_cancel_mid_run_stops_cleanly():
    """Cancel after first completion → run returns, no hang, remaining not
    marked failed (they stay unscraped for next run)."""
```

Implementation notes (differences from the ticket engine — otherwise mirror it):
- No login: `login_once = lambda browser, u, p: True`; supervisor constructed with `username=password=""`.
- Work items are `(space_cfg, article)` tuples; the "tid" for attempts/finished keys is `kb_key(cfg["space_key"], art["slug"])`.
- Per-article pipeline inside the worker's try (replaces `_fetch_ticket`):

```python
async def _scrape_article(page, cfg, art, output_base):
    shot = output_base / cfg["product"] / cfg["lib_folder"] / "screenshots" / f"{art['slug']}.png"
    html = await asyncio.wait_for(
        capture_article(page, art["url"], shot), timeout=ARTICLE_TIMEOUT_S)
    data = parse_article(html, space_key=cfg["space_key"], space_name=cfg["display_name"],
                         product=cfg["product"], title=art["title"], url=art["url"],
                         screenshot_path=str(shot))
    save_article(data, output_base, cfg)
```

  (Wrap ONLY the browser-facing `capture_article` in `wait_for` — parse/save are local CPU work. `asyncio.wait_for` cancels the awaited task on timeout; the page may be in an odd state afterwards, which is fine — the except-path closes and rebuilds it, same as tickets.)
- Success: `state.mark(key)`, per-space `stats["new"] += 1`, `cb.on_status(space_key, stats)`, log `[OK] {title}`. Failure after `MAX_ARTICLE_ATTEMPTS`: `stats["failed"] += 1`, `stats["failed_urls"].append(url)`, append to `failed_articles` with `error_type=type(exc).__name__`.
- Progress: overall counter `done/total` items → `cb.on_progress(cfg["space_key"], art["title"], done, total)`.
- End of run (not cancelled): `generate_kb_index(output_base, KB_SPACES)` in a try/except (log error type on failure); `state.flush()`; write report to `KB_REPORT_FILE` (same file the sync engine used — the tab's Retry button reads it); if `run_audit`: `audit_spaces(scoped_cfgs, output_base)` merged into the report + the audit alert:
  - missing or failed > 0 → `on_alert("warning", "KB scrape finished — items need attention", f"WHAT HAPPENED: {missing} article(s) missing on disk and {failed} failed.\nWHAT TO DO: click 'Retry Failures' to re-scrape exactly those articles.")`
  - both zero → `on_alert("info", "KB scrape complete — library verified", f"All {discovered} discovered article(s) for the scraped spaces are present on disk.")`
- Breaker/give-up alerts: reuse the ticket engine's wording pattern, KB-flavored (no credentials mention — the KB is public; suggest lowering workers / checking network).

- [ ] **Step 4: Run engine tests, full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_kb_engine_async.py -q` (8 passed), then full suite (≥334). Verify `scraper/state/` untouched (hash before/after).

```bash
git add scraper/engine.py scraper/kb_engine_async.py tests/test_kb_engine_async.py
git commit -m "feat(v4.0.4): async parallel KB engine — supervisor recovery, 90s article timeout, audit alert"
```

---

### Task 5: `AsyncKBWorker` (QThread bridge in `scraper/async_runner.py`)

**Files:**
- Modify: `scraper/async_runner.py` (append the new class)
- Test: `tests/test_async_runner.py` (append; note its existing autouse isolation fixture covers the TICKET seam — add a KB-state isolation fixture for the new tests)

**Interfaces:**
- Consumes: `run_kb_scrape_async` (Task 4 signature), `AsyncBrowser`, `app_settings.headless()`, `ResourceSampler` (guarded try/except, same as AsyncTicketWorker).
- Produces:

```python
class AsyncKBWorker(QThread):
    log             = Signal(str, str)
    status          = Signal(str, dict)
    progress        = Signal(str, str, int, int)
    finished_report = Signal(dict)
    alert           = Signal(str, str, str)

    def __init__(self, space_cfgs, *, force=False, workers=4, output_base=None,
                 control=None, items=None):
        ...     # control defaults to RunControl(); exposed as .control
```

  `run()` builds an `EngineCallbacks` subclass forwarding to the signals, a `browser_factory` (`AsyncBrowser(headless=app_settings.headless())`), a guarded sampler, and calls `asyncio.run(run_kb_scrape_async(...))`. `except Exception` → log error (type only) + `alert.emit("error", "KB scrape crashed", ...same WHAT/PRESERVED/DO shape as the ticket crash alert...)` + `finished_report.emit({})`.

- [ ] **Step 1: Write failing tests** (append to tests/test_async_runner.py, following its fake-injection style — check how it injects `browser_factory` into AsyncTicketWorker; AsyncKBWorker needs equivalent injection seams: accept optional `browser_factory=None`, `engine=None` (callable, default `run_kb_scrape_async`) kwargs so tests can stub the engine coroutine entirely):

```python
def test_kb_worker_forwards_signals():
    """Stub engine coroutine that fires cb.on_log/on_status/on_alert and
    returns a report → all four signals observed, finished_report carries
    the report."""

def test_kb_worker_crash_emits_alert_and_empty_report():
    """Stub engine that raises RuntimeError → one alert with 'RuntimeError'
    in body and the message text NOT present; finished_report emitted."""
```

- [ ] **Step 2: Implement, run focused + full suite, commit**

Run: `scraper\venv\Scripts\python.exe -m pytest tests\test_async_runner.py -q`, then full suite (≥336).

```bash
git add scraper/async_runner.py tests/test_async_runner.py
git commit -m "feat(v4.0.4): AsyncKBWorker — Qt bridge for the async KB engine"
```

---

### Task 6: Shared `LogPane` widget extraction

**Files:**
- Create: `scraper/log_pane.py`
- Modify: `scraper/ticket_tab.py` (delegate to LogPane), `scraper/kb_tab.py` (replace `_log` internals)
- Test: `tests/test_log_pane.py`; existing `tests/test_ticket_tab.py` log tests MUST pass unmodified

**Interfaces:**
- Produces: `LogPane(QPlainTextEdit)` — constructor `(max_lines=3000, parent=None)`; `emit_log(level: str, msg: str)` (buffers + forwards to the python `logging` logger "scraper" immediately); `flush()` (drains buffer: one `appendHtml` per line under `setUpdatesEnabled(False)`, per-level colors `#c62828/#ef6c00/#212121`, `&nbsp;`-padded 7-char level, `html.escape(msg)`, scroll to bottom); internal 250ms QTimer started in constructor. This is the EXACT behavior currently in `ticket_tab._emit_log/_flush_log/_LOG_COLORS` — move it, don't reinvent it.
- TicketTab keeps its public seam: `self.log_pane = LogPane(max_lines=self.MAX_LOG_LINES)`, `_emit_log(level, msg)` delegates to `self.log_pane.emit_log(...)`, `_flush_log()` delegates to `self.log_pane.flush()`, `self._log_buf` property maps to the pane's buffer IF the existing tests reference it (check `grep -n "_log_buf\|_flush_log\|_emit_log" tests/test_ticket_tab.py` and preserve exactly what they touch).
- KBTab: `self.log_pane = LogPane(max_lines=self.MAX_LOG_LINES)`; `_log(level, msg)` delegates (keeps its logging-forward semantics — LogPane owns it now).

- [ ] **Step 1: Write failing LogPane tests** (offscreen-Qt pattern from tests/test_ticket_tab.py):

```python
def test_emit_buffers_then_flush_renders_lines_and_blocks():
    """50 emit_log calls → blockCount unchanged; flush() → 50 lines,
    blockCount == 50 (per-line blocks so max_lines caps LINES)."""

def test_flush_escapes_html():
    """emit_log('info', '<script>x</script>') + flush → literal text in
    toPlainText, no raw tag in document HTML."""

def test_max_lines_cap_trims_oldest():
    """max_lines=5, 8 lines flushed → 5 blocks remain, newest content present."""
```

- [ ] **Step 2: Implement LogPane by MOVING the ticket_tab implementation; rewire both tabs; run `tests\test_log_pane.py`, `tests\test_ticket_tab.py` (unmodified, all pass), `tests\test_kb_tab.py`, then full suite (≥339). Commit.**

```bash
git add scraper/log_pane.py scraper/ticket_tab.py scraper/kb_tab.py tests/test_log_pane.py
git commit -m "refactor(v4.0.4): shared buffered LogPane — KB tab gets the bug-144 freeze fix"
```

---

### Task 7: KB tab parity — workers/priority/monitor/alerts + Retry Failures + Audit Library

**Files:**
- Modify: `scraper/kb_tab.py`
- Test: `tests/test_kb_tab.py` (append)

**Interfaces:**
- Consumes: `AsyncKBWorker` (Task 5), `ResourceMonitorWidget` + `ResourceSampler`, `procctl.apply_priority` + `app_settings.priority()/set_priority()`, `run_registry` (already wired), `KB_REPORT_FILE` (engine report with `failed_articles` + `audit.missing`), `audit_spaces`, `KB_SPACES`, `KB_SPACES_BY_KEY`.
- Produces (UI additions, mirroring ticket_tab's exact patterns from Tasks 8-10 of v4.0.3 — read `ticket_tab.py` first):
  - Workers row: `spn_workers` QSpinBox 1-10 (default 4) + live `valueChanged` → if KB worker running: `control.target_workers = value` clamped-message like ticket tab; priority combo (same `_on_priority_changed`/`_reapply_priority`/5s timer, shared `app_settings.priority()`).
  - `self.monitor = ResourceMonitorWidget(sampler=...)` mounted between the progress bar and the log; fed from `_on_progress` (overall done/total) and reset per run.
  - Alert slot `_on_alert(sev, title, body)` — non-modal QMessageBox, ref kept, Pause→Resume flip (same as ticket tab).
  - New buttons in the top action row: `btn_retry = QPushButton("Retry Failures")`, `btn_audit = QPushButton("Audit Library")`. `btn_retry` enabled iff the last report file has failed_articles or audit missing; builds `items=[(KB_SPACES_BY_KEY[m["space_key"]], m), ...]` from the union of `failed_articles` + `audit["...missing..."]` (dedupe by `space_key|slug`) and starts an AsyncKBWorker with `items=` and `force=True`. `btn_audit` runs `audit_spaces(KB_SPACES, app_settings.kb_dir())` on a small QThread (discovery-only, no browser, still registry-guarded), writes `state/kb_audit_report.json`, refreshes btn_retry enablement, and pops the summary alert.
  - KB engine actions (`scrape_space`/`scrape_family`/`scrape_all` KB half/`force`) dispatch through AsyncKBWorker (workers from spinner); Validate/Rebuild-Indexes/RN actions keep the old `_Worker` sync path. The KB→RN "Scrape All" chain: AsyncKBWorker.finished → `_kb_done_start_rn` (same registry hold-through semantics as today).

- [ ] **Step 1: Write failing tests** (append to tests/test_kb_tab.py, following its offscreen fixtures + registry reset; stub AsyncKBWorker where a real run isn't needed):

```python
def test_kb_scrape_uses_async_worker_with_spinner_workers():
    """_scrape_family on a KB family constructs AsyncKBWorker with
    workers == spn_workers.value() (stub the class, capture kwargs)."""

def test_retry_button_builds_items_from_report():
    """Write a fake KB_REPORT_FILE with 2 failed_articles + 1 audit-missing
    (one duplicated) → clicking retry constructs AsyncKBWorker with items
    of length 2+1-1=2... assert exact dedup set and force=True."""

def test_retry_disabled_when_report_clean():
    """Report with no failures/missing → btn_retry disabled."""

def test_audit_button_writes_report_and_enables_retry(monkeypatch, tmp_path):
    """Monkeypatch audit_spaces → result with 1 missing; click audit; report
    file written; btn_retry enabled; alert slot called."""

def test_alert_slot_nonmodal():
    """_on_alert('error','T','B') → _alert_box exists, windowModality() == Qt.NonModal."""
```

- [ ] **Step 2: Implement; run `tests\test_kb_tab.py` + full suite (≥344); commit.**

```bash
git add scraper/kb_tab.py tests/test_kb_tab.py
git commit -m "feat(v4.0.4): KB tab parity — async workers, priority, monitor, alerts, retry + library audit"
```

---

### Task 8: Version 4.0.4 + build assets + docs

**Files:**
- Modify: `scraper/config.py` (APP_VERSION + changelog docstring entry), version test (`grep -rn "4\.0\.3" tests/`)
- Create: `ContosoKBScraper-v4.0.4.spec` (copy v4.0.3 spec, every `4.0.3`→`4.0.4`; psutil hiddenimport already present), `build_scraper_exe_v404.bat` (`--workpath build_v404 --distpath dist`, v4.0.4 spec)
- Modify: `.wolf/buglog.json` (next free IDs: KB frozen-Chrome/no-retry root cause + fix; KB sequential-speed + fix), `.wolf/cerebrum.md` (learnings: per-article wait_for timeout is the frozen-tab killer; LogPane shared widget; kb_key state scheme + read-only migration), `.wolf/anatomy.md` (new files), `.wolf/memory.md` (session line)

- [ ] Version bump + test update; spec + bat; changelog entry dated at this commit (v4.0.4: parallel KB engine, 90s frozen-tab timeout, completeness audit + retry + library audit, KB tab parity — cite the actual commits); buglog/cerebrum/anatomy/memory per the corrections style of v4.0.3's Task 11 (verify buglog JSON validity; cross-reference, don't duplicate).
- [ ] Full suite green (≥344 + any test-count delta), commit:

```bash
git add -A -- scraper/config.py tests/ ContosoKBScraper-v4.0.4.spec build_scraper_exe_v404.bat .wolf/
git commit -m "chore(v4.0.4): version bump, build spec/bat, changelog, buglog + cerebrum learnings"
```

(Deliberate adds only — check `git status` for unrelated untracked files and leave them out.)

---

### Task 9: Live validation + package (GATED — operator confirmation before build)

- [ ] **Step 1: Live smoke (source mode, scratchpad script modeled on val403.py):** one real KB family (e.g. Web 4.0 KB, 4 spaces) at 6 workers headless, isolated state/output → assert saved==discovered (audit clean), sample [OK] lines, pace vs the sequential baseline (expect ≥4x).
- [ ] **Step 2: Frozen-tab / kill-Chrome demo:** mid-run kill the Chrome tree → supervisor recovery, run completes, failed==0. Also verify the post-run audit alert fires.
- [ ] **Step 3: Audit correctness live:** delete one saved article JSON, run Audit Library → exactly that article reported missing; Retry Failures re-scrapes exactly it.
- [ ] **Step 4: STOP — report results and get operator approval (standing rule).**
- [ ] **Step 5: Build (`build_scraper_exe_v404.bat`), frozen-boot check, hand off.**
- [ ] **Step 6: Invoke superpowers:finishing-a-development-branch for the combined v4.0.3+v4.0.4 branch (merge = operator's call).**

---

## Self-Review Notes

- Spec coverage: §3.1→Tasks 3+4, §3.2→Task 2, §3.3→Tasks 1+4+7, §3.4→Tasks 5+6+7, §3.5 respected (no RN/multi work), §6→Tasks 8+9. R2 frozen-tab regression is an explicit named test (Task 4).
- Type consistency: `audit_spaces` result shape used identically in Tasks 1/4/7; `kb_key`/`load_kb_state` in 2/4; `run_kb_scrape_async` kwargs in 4/5; `AsyncKBWorker` signals in 5/7; `LogPane.emit_log/flush` in 6.
- Intent-specified tests (Tasks 4/5/7) name exact assertions and the fixture files whose patterns to follow; all other tasks carry complete code.
