# KB Scraper v4.0.3 — "Big Batch": Auto-Recovery, Speed Auto-Tune, Live Controls & Resource Monitor — Design

**Date:** 2026-07-02
**Branch:** feat/kb-scraper-v4.0.3 (off master @ b39ec76)
**Status:** Approved by operator (2026-07-02)

## 1. Problem

Operator ran v4.0.2 on large batches (19k–30k tickets) and hit, per
`dist/ContosoKBScraper-v4.0.2/state/run.log` (26k lines, runs of 2026-06-30 and 2026-07-02):

1. **Crash #1 (2026-06-30 ~17:12):** 19,001-ticket run @ 9 workers — log stops mid-run,
   no `--- Done`. Operator observed the **window frozen / not responding** and killed it.
2. **Crash #2 (2026-07-02 10:57):** Legacy-tab run of 30,001 @ 10 workers, overlapping a
   still-running tradedesk run of 30,001 @ 8. The shared Chrome died (mass
   `socket.send() raised exception`), every worker's tab-rebuild failed (`rebuild failed —
   worker exiting`), and **28,620 tickets were mass-marked failed** with no popup or
   explanation. The v4.0.2 circuit breaker never fired: workers `break` out on rebuild
   failure *before* the `gate.consume_trip()` check, and no recovery path exists for the
   shared browser itself (`_open_worker_page` in light mode can only
   `shared_browser.new_page()` on a dead browser).
3. **Speed:** ~19 tickets/min on tradedesk @ 8 workers, ~45/min on Legacy @ 10 —
   a 30k batch is 11–26 hours. Contributing waste measured in the log: 7,485 NOT-FOUND
   navigations at full readiness-wait cost; 213 attachment-download timeout failures with
   no retry (`download_all: attachment N/M failed`, `no Download button rendered in time`
   ×164); `state/scraped_tickets.json` (~50KB, OneDrive-synced) rewritten after **every**
   saved ticket; every log line emitted straight into the GUI text widget (30k+ appends on
   a big run — prime suspect for crash #1's UI freeze).
4. **No visibility/control:** no way to see CPU/RAM/Chrome load, no way to raise process
   priority without Task Manager, no way to change workers mid-run, and per-ticket log
   lines show resolution stats but never the main comment-thread count.

## 2. Requirements (operator-confirmed 2026-07-02)

- R1. Per-ticket log line includes main comments/emails count on BOTH portals (content
  capture itself is fine — this is logging only).
- R2. Never mass-fail pending tickets on infrastructure death. Auto-recover (restart
  browser, re-login, resume) unattended; popup + pause only when recovery gives up.
- R3. Popup alerts that explain what happened, why, what's preserved, and what to do.
- R4. Speed: "as fast as possible" AND "current speed OK if it never dies" — i.e.
  auto-tune concurrency to available machine resources; reliability is the floor.
- R5. Resource monitor panel in the scraper: CPU, RAM, Chrome PIDs + memory, workers,
  pace, ETA.
- R6. Live controls while a run is active: process priority (app + Chrome children) and
  worker count.
- R7. One run at a time across all tabs (block + warn), no concurrent portal runs.
- R8. Fix bugs evidenced in the run log (download timeouts, UI freeze, mass-fail).
- R9. Document everything: changelog, buglog, cerebrum, memory; version 4.0.3; one-folder
  exe `dist/ContosoKBScraper-v4.0.3/`; sandbox/live smoke + operator confirmation BEFORE
  the exe build (standing rule).

## 3. Design

### 3.1 BrowserSupervisor — engine-level auto-recovery (R2)

New class in `scraper/ticket_engine_async.py` (or `scraper/supervisor.py`) owning the
light-mode shared browser:

- `await supervisor.page()` → new page from the live browser.
- On any worker error where the browser is dead (page-rebuild raises), the worker calls
  `await supervisor.recover(reason)`. Exactly ONE recovery runs (asyncio.Lock): close the
  dead browser, `browser_factory().open()`, `login_once(...)`, generation counter += 1.
  Other workers block on the same lock and re-check the generation — they don't each
  restart Chrome.
- Bounded: max 3 consecutive failed recoveries (reset on any success) within the run →
  supervisor gives up → **pause the run** (`control.pause()`), emit
  `on_alert(...)` — pending tickets stay queued; Resume retries recovery.
- Session-expired (`_SESSION_EXPIRED`) routes through the same recovery (re-login on the
  existing browser first; full restart if that fails).
- Workers NEVER exit on rebuild failure anymore; they wait on recovery and continue.
  A worker exits only on cancel or queue-empty. `drain_to_failed` remains ONLY for
  cancel-time leftovers (existing behavior) and startup login failure.
- Circuit breaker: `gate.consume_trip()` check moves so it is evaluated on every failure
  path (including post-recovery), and the breaker pause now ALSO raises `on_alert`.
- Multi-window mode: unchanged per-worker browsers, but the same never-mass-fail rule —
  a worker that cannot rebuild its own browser asks the supervisor for a global pause
  decision instead of silently exiting when it is the last worker.

### 3.2 Alerts (R3)

- `TicketEngineCallbacks.on_alert(severity, title, body)` — new callback, default no-op.
- GUI: non-blocking `QMessageBox` (app-modal=False) from the main thread via signal.
  Body template: WHAT happened / WHY (likely cause) / WHAT IS PRESERVED (saved count,
  progress persisted, resume works) / WHAT TO DO.
- Raised on: recovery give-up, circuit-breaker pause, startup login failure, run finish
  with failed > max(50, 10% of batch), and engine coroutine crash.
- Alert text goes to run.log too (INFO/ERROR mirror), exception TYPES only, no PII.

### 3.3 Resource-aware auto-tune (R4)

`scraper/throttle.py` AdaptiveGate v2:

- New inputs each adjustment tick: system CPU% and available RAM via `psutil`
  (sampled by a lightweight monitor task every ~2s), plus existing timeout/error rate.
- Policy: target in-flight concurrency steps UP (toward the operator ceiling) when
  CPU < ~75% and free RAM > ~1.5GB and error rate low; steps DOWN on CPU > ~90%
  sustained, free RAM < ~800MB, or timeout burst (existing behavior). Floor 1.
- The operator's worker slider value is the ceiling; auto-tune never exceeds it.
- `psutil` added to requirements + PyInstaller spec (it's a plain C-extension wheel,
  PyInstaller-safe).

### 3.4 Speed fixes from log evidence (R4, R8)

- **State-write batching:** `_mark_scraped` appends to an in-memory set and a small
  journal; the full `scraped_tickets.json` rewrite happens every 25 saves or 10s
  (whichever first) + once at run end + on cancel. Crash-safety: journal (`.jsonl`
  append) replayed on load so a hard kill loses nothing.
- **Download retry:** each attachment download gets up to 2 retries with short backoff;
  per-download timeout tuned; a failed download logs and continues (never fails the
  ticket) — counts surface in the per-ticket log line.
- **NOT-FOUND fast path:** detect the redirect-to-list (tradedesk `/bugs`) / legacy
  not-found signature with a short dedicated wait instead of the full ticket readiness
  wait.
- **GUI log batching (freeze fix):** worker log lines buffer in the GUI and flush on a
  250ms QTimer as a single append; the log widget keeps at most ~5,000 lines (older
  trimmed; full detail remains in state/run.log). Progress-bar/stats updates already
  throttled; verify with a synthetic 30k-line flood test.
- Worker hard cap stays 10 visible in UI; auto-tune governs in-flight below the ceiling.

### 3.5 Live run controls (R6)

- **Priority selector** (Low / Normal / High) in the Tickets tab run row, enabled always:
  new `scraper/procctl.py` uses `psutil` to set the priority class of the app process and
  all live Chrome children (`children(recursive=True)`), re-applied every monitor tick
  (~5s) so newly-spawned Chrome processes inherit the choice. Windows classes:
  BELOW_NORMAL / NORMAL / ABOVE_NORMAL+HIGH boundary — "High" maps to ABOVE_NORMAL for
  Chrome children and HIGH for the app (full HIGH on Chrome can starve the desktop).
  Persisted in app_settings.
- **Live worker slider:** existing workers spinbox becomes live: during a run it updates
  `gate` ceiling + a shared `target_workers`; parked workers (idx ≥ target) idle-wait
  cheaply; raising the target wakes/spawns up to the max started for the run (workers
  above the run's starting count are spawned on demand up to 10).

### 3.6 Resource monitor panel (R5)

Collapsible panel on each Tickets tab (one shared widget class):

- Refresh 2s via QTimer on the GUI thread, data from a psutil sampler (cached, cheap).
- Rows: System CPU % • System RAM used/total • App RAM • Chrome: N processes,
  total RSS MB (+ expandable per-PID list: PID, RSS) • Active workers / in-flight •
  Pace (rolling 3-min tickets/min) • ETA for remaining queue • Saved/NF/Failed.

### 3.7 Single-run guard (R7)

`scraper/run_registry.py` — tiny module-level registry (`acquire(tab_name)` /
`release()`). Every tab's Start handler acquires; if busy → warning dialog naming the
tab that owns the run; Start blocked. Released in the worker's finished handler
(and on engine crash).

### 3.8 Comments in per-ticket log (R1)

`[OK] #{tid}: {title} — {C} comment(s)/email(s), resolution {R} chars, {F} file(s)`
emitted from the engine (portal-agnostic — both portals flow through
`run_ticket_scrape_async`). The existing resolution sub-line stays at DEBUG-equivalent
detail level.

## 4. Error handling

- All new failure paths log exception TYPE only (no messages — org policy, no PII).
- Recovery attempts/generations logged with counts so post-mortems are possible from
  run.log alone.
- Alert dialogs never block the engine (queued signal to GUI thread).
- psutil failures (process gone mid-iteration) are swallowed per-process
  (`NoSuchProcess`) — monitoring must never take down a run.

## 5. Testing

- TDD per component; suite currently 260 green — target ≥ 290.
- Unit: supervisor single-flight recovery, bounded give-up → pause+alert (no mass-fail);
  breaker fires on worker-exit path; gate auto-tune step up/down vs fake psutil inputs;
  live ceiling change; state-write batching + journal replay after simulated kill;
  download retry; NOT-FOUND fast path; run-registry blocking; log-buffer flush + trim;
  procctl priority mapping with mocked psutil; comment-count log line.
- GUI: alert routed via signal (offscreen); monitor panel renders with fake sampler;
  synthetic 30k-line log flood stays responsive (flush count bounded).
- Live validation (pre-build, operator-confirmed): one tradedesk + one Legacy batch
  (~200 tickets each, headless, auto-tune on), then a deliberate Chrome-kill mid-run to
  demonstrate auto-recovery + resume, and a breaker/give-up popup demo.

## 6. Ship

- Version 4.0.3 everywhere (About, title, spec name).
- CHANGELOG entry; buglog.json entries: UI freeze (crash #1), shared-browser death
  mass-fail (crash #2), download-timeout no-retry, per-save state rewrite; cerebrum
  learnings; .wolf/memory.md session summary.
- One-folder build → `dist/ContosoKBScraper-v4.0.3/` via fresh `--workpath build_v403`
  (OneDrive rule), frozen-boot check, then operator hand-off.

## 7. Out of scope

- Concurrent multi-portal runs (explicitly rejected — single-run guard instead).
- Queued back-to-back runs (operator picked "one at a time is fine").
- KB-tab engine changes (sync engine untouched beyond shared widgets).
- Any crypto/API replay on the encrypted tradedesk channel (standing rule).
