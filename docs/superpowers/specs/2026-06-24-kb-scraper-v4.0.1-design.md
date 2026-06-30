# KB Scraper v4.0.1 — Async Dual-Portal + Stability — Design

**Status:** approved (design) 2026-06-24. Supersedes the live worker model of v4.0.
**Branch:** to be created `feat/kb-scraper-v4.0.1` off `master` (v4.0 merged at `fef7fa4`).

## Goal

Make ticket scraping **reliable under load** and cover **both support portals**:

1. Fix the new-portal (portal.contoso.example) instability — under high worker counts many headed Chrome instances saturate the machine (screen freezes, Chrome lag) and tickets fail "the majority of the time."
2. Re-architect the browser/engine layer on **async Playwright** with two user-selectable worker modes (a light single-window default + a multi-window toggle).
3. Add a **Legacy tab** for the old portal (support.contoso.example, ASP.NET) and bring its extraction to **full parity** with the new portal (ticket details, comments, comment images, files, and the resolution's own comments + files).
4. **Validate parity** across both portals, version **4.0.1**, and package one-folder into **`dist/ContosoKBScraper-v4.0.1/`**.

## Background

- **New portal** = portal.contoso.example — modern JS SPA, API end-to-end AES-GCM encrypted → rendered-DOM scraping only. Current v4.0 scraper works on golden tickets **76511** (resolution + files) and **76091** (comment images + files) but is unreliable under load.
- **Old portal** = support.contoso.example — ASP.NET WebForms (`edit_bug.aspx`, `Resolution.aspx`), still **live, same login, holds tickets**. Its scraper exists in git history at commit **`a718c81`** ("feat(v3.1): ticket portal scraper … parallel workers, resolution skip, inline attachments") — to be revived and raised to parity.
- **Both portals share ticket IDs** (the system migrated): 76511 + 76091 exist on both, enabling a field-for-field cross-portal comparison. Series **71456–71467** (12 tickets) is the batch/load test.

## Root cause of the v4.0 instability

`run_ticket_scrape` spawns **one full Chrome process per worker** (synchronous Playwright, one thread each). At 10 workers that is ~10 Chrome processes → RAM/CPU saturation → whole-machine freeze and Chrome lag; crashed tabs (already mitigated in v4.0 by the shared-queue redispatch, commit `aec1536`) still leave the machine thrashing. Synchronous Playwright objects cannot be driven across threads, so "one window, many concurrent tabs, one login" is impossible without moving to **async Playwright**.

## Architecture — async-unified, shared schema

- **Async Playwright** in a single asyncio event loop owned by a worker `QThread`. The thread emits Qt signals (queued connections) for progress/status/log so the GUI thread never blocks. No Playwright object crosses threads.
- **Parsers stay synchronous** — pure BeautifulSoup functions on captured HTML, no I/O. Both portals' parsers emit the **same canonical ticket dict**, so parity is structural-by-construction and one writer serves both.
- The v4.0 sync engine's crash-resilience (shared queue → bounded redispatch → in-place rebuild → drain-to-failed → exactly-once terminal status, PII-clean logs) is **ported to async** (asyncio.Queue + N worker coroutines). It is the blueprint, not throwaway.

### Canonical ticket schema (both portals emit this)
```
ticket = {
  "id": str, "title": str, "url": str,
  "fields": { ... portal fields ... },
  "comments": [ { "author": str, "date": str, "body": str,
                  "images": [ {mime, saved_path} ], "attachments": [ {label, saved_path} ] } ],
  "resolution": { "text": str, "comments": [ <same shape as comments> ],
                  "attachments": [ {label, saved_path} ] },
  "attachments": [ {filename, saved_path} ]   # top-level files
}
```
Raw base64 image data is decoded to files by the writer and never written into JSON.

## Components

| File | Responsibility |
|------|----------------|
| `scraper/portal/async_browser.py` (new) | Async Chrome wrapper — launch system Chrome (`channel="chrome"`), context/page lifecycle, downloads. |
| `scraper/portal/base_portal.py` (new) | Async portal Protocol: `login`, `open_ticket`, `subview_count`-equivalent, `parse → ticket dict`, `download_all`, `is_login_page`, `is_not_found`. |
| `scraper/portal/tradedesk_portal.py` (rewrite) | Async SPA adapter — port current logic + reliability fixes from the live session. |
| `scraper/portal/contoso_portal.py` (new) | Async old-portal adapter — revived from `a718c81`, raised to parity. |
| `scraper/parsers/tradedesk_parser.py` | Existing SPA parser, emit canonical schema (resolution comments/files added if missing). |
| `scraper/parsers/contoso_parser.py` (new) | Old-portal cells-based parser revived from `a718c81`, emit canonical schema. |
| `scraper/ticket_engine_async.py` (new) | Async engine: asyncio.Queue, N worker coroutines, two modes, ported resilience. Retires the sync `ticket_engine.py` live path. |
| `scraper/writers/ticket_writer.py` | Shared JSON+MD + image/file save (already exists; confirm both schemas write cleanly). |
| `scraper/ticket_tab.py` / new `legacy_tab.py` | Two ticket tabs (tradedesk + legacy) sharing controls. |
| `scraper/settings_dialog.py` | Add Browser-mode toggle. |
| `scraper/app_settings.py` | Persist `browser_mode` ("light" | "multi"). |

## Two worker modes (Settings toggle; worker-count slider drives both)

- **Light (default):** 1 Chrome window, **one login**, N concurrent **tabs** (N pages in a shared authenticated context). Lightest footprint — removes the freeze. N = worker slider.
- **Multi-window (toggle on):** N separate Chrome windows, each logs in independently (today's behaviour) for isolation/visibility. N = worker slider.
- Both modes use the same asyncio engine, queue, and crash-resilience; they differ only in how the per-worker page is provisioned (shared-context tab vs own-browser).

## GUI

Tabs: **Tickets — tradedesk** · **Tickets — Legacy** · **Knowledge Base**. Both ticket tabs share controls (worker slider 1–N, Pause/Resume/Stop via RunControl, output folder from Settings, 4-col table Ticket#/Status/Title/Files). Settings adds the **Browser mode** toggle (Light default). Close drains all running tabs.

## New-portal reliability — live diagnosis

The "fails most of the time" symptom needs **systematic-debugging in a guided live session**, not a guessed fix. The async light mode removes resource saturation; separately, trace render/timing/selector failures on real runs and fix root causes (condition-based waits, the redispatch retries, re-login on session expiry). Confirm on golden tickets before declaring fixed.

## Parity & validation

- **Cross-portal field-for-field:** scrape 76511 + 76091 from **both** portals; assert the same categories populated (ticket fields, comments, comment images, files, resolution text + resolution comments + resolution files) and that shared-ticket data matches.
- **Batch/load:** 71456–71467 in light mode → zero stranded tickets, no freeze, completeness holds.
- **Unit tests:** PII-free synthetic fixtures for the contoso parser mirroring the tradedesk parser suite; async-engine tests for queue/redispatch/two-modes (fake async portal).

## Security & constraints (carried from v4.0, non-negotiable)

- Password → OS keyring only; never on disk, never logged, never in process args. Settings store only portal_url + username + output paths + browser_mode.
- No customer PII / secrets in logs (log exception **type** only, never messages that may carry data).
- **Operator-confirmed smoke/live run before any exe build** (standing rule).
- System Chrome via `channel="chrome"` — no bundled browser.

## Versioning & packaging

`APP_VERSION → 4.0.1`. `ContosoKBScraper-v4.0.1.spec` (one-folder COLLECT, entry `scraper/app.py`, `--distpath dist`, COLLECT name `ContosoKBScraper-v4.0.1`, icon `assets/scraper_icon.ico`, heavy-Qt excludes, `collect_all` playwright+PySide6). Frozen `BASE_DIR = _EXE_DIR.parent.parent` unchanged (exe at `dist/ContosoKBScraper-v4.0.1/` is still two levels under repo root). Retire `dist-v4/`.

## Phases (each gets its own plan; worst pain first)

1. **Async core + new-portal light mode + live reliability fix.** async_browser + base_portal + async tradedesk adapter + async engine (light mode) + RunControl/pause carried over; live-debug new-portal failures; prove reliable + light on 76511/76091 + 71456–71467. Sync engine retired.
2. **Multi-window mode + Settings toggle.** Browser-mode toggle, worker-count wired to both modes, both drained on close.
3. **Old-portal async adapter + contoso parser at full parity + Legacy tab.** Revive `a718c81`, async-port, canonical schema, fixtures + unit tests, Legacy tab.
4. **Parity validation + package 4.0.1.** Cross-portal 76511/76091 + 71456–71467 batch; version bump; one-folder build into `dist/ContosoKBScraper-v4.0.1/`; operator-confirmed smoke → build → frozen-boot + load verify; finish branch.

## Success criteria

- Light mode default: scraping 12 tickets at the chosen worker count does **not** freeze the machine and strands **no** tickets.
- Both portals produce the **same categories** of data on 76511 + 76091, with shared-ticket data matching.
- New portal scrapes reliably (golden tickets + series) in a live run the operator confirms.
- 4.0.1 one-folder exe in `dist/ContosoKBScraper-v4.0.1/` opens < 1 min, correct icon, both portals work, no credentials on disk/in logs.

## Open risks

- Async rewrite is the largest change; mitigated by phasing (new portal proven before old portal) and keeping the pure parsers/writer reusable.
- Old-portal DOM may have drifted since `a718c81`; confirmed/fixed live during Phase 3.
- "Resolution comments" exact markup per portal verified live; schema already accommodates it.
