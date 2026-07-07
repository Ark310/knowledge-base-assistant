# KB Scraper v4.0.4 — "KB Parity + Finalize": Async Parallel KB Engine, Completeness Audit, Tab UI Parity — Design

**Date:** 2026-07-07
**Branch:** feat/kb-scraper-v4.0.3 (continues; version becomes 4.0.4)
**Status:** Approved by operator (2026-07-07)

## 1. Problem

Operator tested v4.0.3: ticket tabs "work like a charm"; the Knowledge Base tab does not:

1. **Slow:** the KB engine (`scraper/kb_engine.py`) is fully sequential — one sync
   Browser, one article at a time (navigate → expand macros → screenshot → parse →
   save) across 43 Confluence spaces. No workers concept at all.
2. **Freezes:** operator observed the Chrome window freeze AND the app freeze during a
   KB run, and the in-flight article was **not retried**. Root causes: no per-article
   timeout (a frozen — not crashed — Chrome hangs `navigate`/`expand`/`screenshot`
   forever; `browser.is_alive()` is only checked after an exception that never comes),
   and the KB tab still has the v4.0.2-era per-line log rendering
   (`kb_tab._log` does per-line `insertText` + `ensureCursorVisible`) that froze the
   ticket tabs (bug-144) — never ported.
3. **No completeness assurance:** failures live in `state/last_kb_run_report.json`
   nobody reads; there is no discovered-vs-on-disk verification, no retry affordance,
   no popup when something is missed.
4. **No visibility:** no workers/pace/resource display; log pane lags behind.

## 2. Requirements (operator-confirmed 2026-07-07)

- R1. Parallel workers for KB scraping with **full ticket-tab parity**: workers 1–10 +
  live slider, resource auto-tune, monitor panel, priority control, headless setting,
  popup alerts, auto-recovery when Chrome dies or freezes.
- R2. A frozen Chrome/tab must never hang the run and must never silently lose the
  in-flight article (hard per-article timeout → bounded retry → failure recorded).
- R3. Completeness, all three layers: (a) post-run audit (discovered vs on-disk) with
  summary popup; (b) Retry Failures button (failed + missing only); (c) on-demand
  Audit Library action verifying the whole existing library against live discovery.
- R4. Logs visible and current: buffered per-line-block log flush (bug-144 fix) in the
  KB tab; per-article log lines preserved.
- R5. Release Notes engine stays as-is (KB spaces only); RN still benefits from the
  log-pane fix.
- R6. Version 4.0.4; suite green; live validation incl. Chrome-kill + audit
  correctness; exe build gated on operator confirmation (standing rule); then finalize
  the branch (merge decision is the operator's, covering v4.0.3 + v4.0.4 together).

## 3. Design

### 3.1 Async KB engine — `scraper/kb_engine_async.py` (R1, R2)

Mirrors `ticket_engine_async.py` structure, reusing its proven primitives verbatim
where possible:

- **Discovery phase (fast, unchanged mechanism):** for the selected scope (one space /
  one family / all), call `discover_articles(space_key)` (REST pagination) per space
  up front. Build ONE `asyncio.Queue` of work items `(space_cfg, article)`. Per-space
  `discovered` counts emitted immediately (existing `on_status` shape — the detail
  table fills as today). A space whose discovery fails is reported (`on_log` error +
  audit entry) and its articles are absent from the queue.
- **Workers (light mode only):** one shared `AsyncBrowser` (respects
  `app_settings.headless()`) managed by the existing **`BrowserSupervisor`** with a
  no-op `login_once` (the KB is public — supervisor keeps its restart/single-flight/
  give-up semantics). Each worker owns one tab. Workers pull articles, and each
  article is processed inside **`asyncio.wait_for(..., ARTICLE_TIMEOUT_S = 90)`** so a
  frozen tab raises `TimeoutError` instead of wedging the run (R2).
- **Per-article pipeline (async ports of the sync steps):** `goto(url,
  domcontentloaded)` → `expand_macros(page)` (async port of
  `core.Browser.expand_confluence_macros`) → `page.screenshot(path)` →
  `parse_article(html, ...)` (reused unchanged) → `save_article(...)` (reused
  unchanged) → `tracker.mark(space_key, slug)`.
- **Resilience (identical semantics to tickets):** bounded attempts
  (`MAX_ARTICLE_ATTEMPTS = 3`, shared-queue redispatch), page rebuild via supervisor,
  worker never exits on infra failure, give-up → pause + ONE alert, breaker +
  `AdaptiveGate` + tuner task (`sampler`, `control.target_workers` ceiling), parked
  workers exit when active slots dead, cancel-drain only. Failed articles: never
  marked scraped, recorded as `{space_key, title, url, error_type}` in the run report.
- **Run end:** `rebuild_indexes()` once, `_write_report` (existing shape + a
  `failed_articles` list + audit result), then post-run audit (3.3) and its alert.
- **Callbacks:** the existing `EngineCallbacks` surface (`on_log/on_status/
  on_progress/on_started/on_finished`) is kept for the tab's table/progress wiring,
  plus `on_alert(sev, title, body)` added to `EngineCallbacks` (same no-op default
  pattern as `TicketEngineCallbacks`).

### 3.2 Scraped-state: journaled batched tracker (R2, speed)

`KB_ARTICLES_STATE_FILE` currently rewrites the whole JSON per article
(`StateTracker`). The async engine uses the existing **`ScrapedState`** with keys
`"{space_key}|{slug}"` and a KB-specific state file. One-time migration: if the legacy
tracker file exists and the new one doesn't, seed the new file from it (no forced
re-scrape). The sync `StateTracker` and its file stay untouched for the RN engine.

### 3.3 Completeness audit — `scraper/kb_audit.py` (R3)

Pure, testable module:

- `audit_spaces(space_cfgs, output_base, discover=discover_articles) -> AuditResult`:
  per space, list discovered articles, check the expected JSON file exists on disk
  (`output_base/product/lib_folder/slug.json` — same path logic as `save_article` via
  a shared helper), return per-space `{discovered, on_disk, missing: [article...]}`.
- **Post-run audit:** runs automatically after every KB scrape over the spaces in
  scope; result merged into the run report; completion alert popup:
  "X discovered / Y on disk / Z missing / F failed — Retry Failures re-scrapes them".
  Missing==0 and failed==0 → info-level popup confirming completeness.
- **Retry Failures button (KB tab):** enabled when the last report has failures or
  missing; scrapes exactly that article set (a work-queue of specific articles —
  the engine accepts an explicit item list as an alternative to space scope).
- **Audit Library button (KB tab):** on demand, `audit_spaces` over ALL 43 spaces
  (discovery only — no browser), report written to `state/kb_audit_report.json`,
  results popup + offer wording pointing at Retry Failures (which after an audit
  targets the audit's missing set).

### 3.4 KB tab UI parity (R1, R4)

- **Shared widgets extracted once, reused by both tabs:** the buffered log pane
  (timer flush, per-line blocks, level colors, HTML-escaped, line cap) becomes
  `scraper/log_pane.py` (`LogPane` widget); TicketTab and KBTab both use it
  (TicketTab's internal implementation moves there — behavior pinned by existing
  tests). `ResourceMonitorWidget` is instantiated in KBTab as-is; the priority combo
  + reapply timer pattern is reused.
- **KBTab additions:** workers row (spin 1–10, live → `control.target_workers`),
  priority combo, monitor panel (pace = articles/min, ETA from queue), Retry Failures
  + Audit Library buttons in the top action row, alert slot (non-modal QMessageBox,
  Pause→Resume flip when engine self-paused).
- **Worker thread:** new `AsyncKBWorker(QThread)` in `scraper/async_runner.py`
  (sibling of AsyncTicketWorker): signals `log/status/progress/finished_report/alert`,
  runs `run_kb_scrape_async` via `asyncio.run`. The KB tab's `_Worker`/engine
  dispatch switches to it for KB actions; RN actions keep the old `_Worker` + sync
  engine. Single-run registry unchanged (already wired).
- Table/status behavior unchanged (per-space counts update as articles finish);
  progress label shows overall `done/total` articles plus current space.

### 3.5 Out of scope

- Release Notes engine internals (R5), ticket tabs (no changes), multi-window mode
  for KB (light only — Confluence needs no login; multi adds nothing), KB Validate /
  Rebuild Indexes actions (kept on the sync path they use today — Validate is
  discovery-only HTTP, no browser).

## 4. Error handling

- Exception TYPES only in logs (org policy) — including timeout/audit paths.
- Audit/discovery failures never crash a run; they mark the space in the report and
  alert at the end.
- Alert popups are non-modal; engine never blocks on GUI.
- State migration is read-only on the legacy file (never deleted/rewritten).

## 5. Testing

- TDD per component; suite 315 green now — target ≥ 345.
- Engine: fake async pages/browser fixtures (mirror test_ticket_engine_async.py):
  parallel completion, frozen-page timeout → redispatch → bounded fail, supervisor
  recovery on browser death, never-mass-fail, park/tuner reuse, explicit-item-list
  runs (retry path), per-space status aggregation. State: ScrapedState key scheme +
  legacy migration. Audit: missing-detection, empty-space, discovery-failure. UI:
  LogPane extraction pinned by existing ticket-tab tests + new KB tests (buttons,
  alert slot, workers row). All test files driving engines get their own state
  isolation fixture (bug-149 rule).
- Live validation (pre-build, operator-gated): one real KB family (parallel, headless),
  deliberate Chrome kill mid-run → recovery, audit report correctness vs disk, pace
  comparison vs sequential baseline.

## 6. Ship

- Version 4.0.4 everywhere; changelog entry (config.py docstring); buglog entries
  (KB freeze/no-retry root cause; sequential-engine speed); cerebrum learnings;
  anatomy/memory updates.
- Build `dist/ContosoKBScraper-v4.0.4/` (spec copy, `--workpath build_v404`), frozen
  boot check, operator hand-off; then finishing-a-development-branch for the combined
  v4.0.3+v4.0.4 branch (merge = operator's call).
