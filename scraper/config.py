from pathlib import Path
import sys

APP_VERSION = "4.0.4"
"""
Changelog
─────────
v4.0.4 2026-07-07  KB tab parity with the ticket tabs — parallel async engine, a
                   hard per-article timeout, and three-layer completeness. Fixes:
                   (a) a frozen (not crashed) Chrome tab could silently swallow an
                   in-flight article forever — the old sequential sync engine had
                   no per-article timeout, and is_alive() is only checked after an
                   exception a hang never raises; a new async parallel KB engine
                   (scraper/kb_engine_async.py) wraps each article in a 90s
                   asyncio.wait_for, backed by BrowserSupervisor auto-recovery, and
                   never marks a timed-out article as scraped (bug-161, commit
                   5cb46d7); (b) KB scraping was one-article-at-a-time and the tab's
                   log never got the bug-144 buffered-log freeze fix ported over —
                   fixed with N parallel workers (light mode, 1 shared Chrome) and
                   the same shared LogPane widget the ticket tabs use, so per-line
                   QPlainTextEdit inserts can no longer repaint-storm the UI
                   (bug-162, commits 5cb46d7, 1b77510); (c) no way to tell a
                   partial KB run from a complete one — a discovered-vs-on-disk
                   completeness audit (scraper/kb_audit.py) now runs after every
                   scrape and surfaces gaps via "Retry Failures" (re-run only the
                   missing articles) and an on-demand "Audit Library" button
                   (aff8c08, b875eaf). Also: journaled KB scraped-state
                   (scraper/kb_state.py, "{space_key}|{slug}" keys) with a
                   one-time read-only migration from the legacy on-disk layout
                   (450d120); async Confluence page ops — navigate/expand/
                   screenshot (7db3735); AsyncKBWorker Qt bridge (d071ce1); KB tab
                   gets the same live worker slider, priority control, and
                   resource monitor panel as the ticket tabs, plus popup alerts on
                   pause/stop (b875eaf); review-pass fixes for audit-crash
                   alerting, dispatch coverage, an honest stop, and a run summary
                   (5bcd08f).
v4.0.3 2026-07-03  Auto-recovery + operator visibility (no more mass-fail). Fixes:
                   (a) a big-batch GUI freeze — a 19k-ticket run made the window
                   go "not responding" from per-line log appends + pre-creating
                   19k QTableWidget rows; fixed with buffered log flushing +
                   lazy table rows (bug-144, see also bug-139/bug-142); (b)
                   BrowserSupervisor (scraper/supervisor.py) gives the shared
                   light-mode Chrome single-flight restart+relogin recovery — a
                   30k-ticket run mass-failed 28,620 tickets when the browser
                   died and no path recovered it (2026-07-02 10:57); the run now
                   pauses + alerts instead of draining (bug-145, see also
                   bug-123); (c) speed waste — 213 one-shot download timeouts and
                   7,485 NOT-FOUND tickets paying the full wait cost, plus a full
                   ~50KB state-file rewrite per saved ticket; fixed with download
                   retries, a 250ms-poll NOT-FOUND fast path, and batched
                   journaled state writes (bug-146); (d) a breaker pause used to
                   be log-only with no operator-visible explanation; explanatory
                   popup alerts (WHAT/WHY/PRESERVED/DO) now fire on every
                   pause/stop (bug-147). Also: resource auto-tune + a live
                   monitor panel (system/app/Chrome CPU+RAM, pace/ETA), process
                   priority control (app HIGH, Chrome children capped at
                   ABOVE_NORMAL so the desktop doesn't starve), a live
                   worker-count slider (park/unpark mid-run), and a single-run
                   guard so only one scrape runs at a time across all tabs.
v4.0.2 2026-06-30  Robust large-batch scraping (bug-111: an 18k-ticket @ 10-worker run
                   collapsed — 0 saved). Fixes: (a) the per-worker failure budget is now
                   CONSECUTIVE (reset on success) — it was a lifetime counter that
                   guaranteed pool collapse on big batches; (b) a Headless browser toggle
                   in Settings (far lighter per tab — validated headless@5 = 99 saved/0
                   timeouts vs 0 saved headed@10); (c) an adaptive concurrency gate +
                   backoff that throttles load on a timeout burst instead of saturating
                   the shared Chrome; (d) a circuit breaker that PAUSES + alerts on
                   sustained failure rather than mass-failing; (e) periodic tab recycling
                   for long-run endurance; (f) a batched fail-drain so a collapse can't
                   flood/hang the UI. Also tradedesk email entries are now captured (bug-106).
v4.0.1 2026-06-29  Async rewrite (feat/kb-scraper-v4.0.1): default LIGHT mode (one
                   Chrome window, one login, N tabs) fixes the high-worker freeze, with
                   a multi-window Settings toggle; resolution file/thread completeness;
                   added a Legacy support.contoso.example portal tab at parity (internal
                   comments + view_attachment.aspx files). Packaged to dist/.
v4.0  2026-06-23  Major overhaul (in progress on feat/kb-scraper-v4):
                   A) Support portal moved support.contoso.example → portal.contoso.example
                      (encrypted JS SPA): rebuilt ticket scraping on a TradeDeskPortal
                      adapter (rendered-DOM extraction), capturing fields, comments,
                      resolution text+file, comment files, and inline comment images.
                   B) RunControl Pause/Resume + Stop; parallel workers 1–10.
                   C) Brand theme (chatbot palette), animated splash, ice-scraper icon,
                      branded top bar, Settings dialog (per-type output folders + hidden
                      portal credentials).
                   (Tickets/KB tab restyle = Phases 4–5; one-folder packaging = Phase 6.)
v3.1  2026-06-10  Ticket Portal enhancements:
                   A) Parallel workers (1-4 configurable in GUI) — each worker opens
                      its own headed Chrome, logs in independently; state file writes
                      protected by threading.Lock.
                   B) Resolution skip — only fetches Resolution.aspx when the ticket
                      detail page shows "Resolution(filled)"; saves one page load per
                      ticket without a resolution.
                   C) Inline attachment capture — extracts base64-encoded images
                      embedded in comment/email bodies (data:image/... URIs), saves
                      them as files to library/tickets/attachments/{id}/, and stores
                      paths in JSON; raw base64 never written to disk.
v3.0  2026-06-09  Ticket Portal scraper (Tab 3): ingest tickets + resolutions from
                   support.contoso.example into library/tickets/; OS-keyring credential
                   storage; single/multi/range ticket input; browser auto-restart.
v2.6  2026-06-09  Browser freeze fix: changed wait_until from networkidle to
                   domcontentloaded; added Browser.is_alive() + restart() for
                   automatic recovery from Chrome crashes mid-scrape.
v2.5  2026-06-03  KB config overhaul: added FIX Protocol/Distribution Layer (TradeDesk),
                   8 missing SalesHub spaces, new FormFlow KB product group (moved
                   SF* spaces from saleshub), relabeled Web 2.0 → Web 2.5.
v2.0  2026-06-01  Full-site KB scraper (Tab 2): 43 Confluence spaces, JSON+MD output.
v1.0  2026-05-27  Release notes scraper (Tab 1): TradeDesk, Web4, SalesHub.
"""

# ── Paths ─────────────────────────────────────────────────────────────────────
# When frozen as a PyInstaller exe, __file__ points inside a temp extract dir;
# library/state must sit next to the executable instead.
if getattr(sys, "frozen", False):
    _EXE_DIR  = Path(sys.executable).parent          # .../dist-v4/ContosoKBScraper-v4/
    # one-folder layout: exe-dir -> dist-v4 -> project root. Output folders are
    # user-overridable in Settings; this default writes to the existing library/
    # when the exe runs in-place under the project.
    BASE_DIR  = _EXE_DIR.parent.parent                # project root
    STATE_DIR = _EXE_DIR / "state"                    # writable, next to the exe
else:
    BASE_DIR  = Path(__file__).parent.parent           # Knowledge Base/
    STATE_DIR = Path(__file__).parent / "state"
LIBRARY_BASE = BASE_DIR / "library"
STATE_FILE   = STATE_DIR / "scraped_versions.json"
LOG_FILE     = STATE_DIR / "run.log"
REPORT_FILE  = STATE_DIR / "last_run_report.json"

BASE_URL = "https://help.contoso.example"

# ── Products ──────────────────────────────────────────────────────────────────
# space_key values verified live on 2026-05-27. release_notes_url is derived as
# f"{BASE_URL}/display/{space_key}". The --discover command can re-derive and
# rewrite release_notes_url robustly, but these defaults work out of the box.
PRODUCTS: dict[str, dict] = {
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
    "web4": {
        "display_name": "Web4",
        "space_key": "ReleaseNotesWeb4",
        "release_notes_url": "https://help.contoso.example/display/ReleaseNotesWeb4",
        "section_aliases": {
            "enhancements": ["enhancements and new features", "enhancements", "new features"],
            "bugs": ["bugs", "bug fixes"],
            "schema_changes": ["schema changes", "database changes"],
            "tasks": ["tasks"],
        },
    },
    "saleshub": {
        "display_name": "SalesHub",
        "space_key": "SHReleaseNotes",
        "release_notes_url": "https://help.contoso.example/display/SHReleaseNotes",
        "section_aliases": {
            "enhancements": ["enhancements and new features", "enhancements", "new features"],
            "bugs": ["bugs", "bug fixes"],
            "schema_changes": ["schema changes", "database changes"],
            "tasks": ["tasks"],
        },
    },
}

# Canonical column normalization for release-note tables.
# Keys are lowercased, whitespace-collapsed header text. The Risk column header
# is a long blob beginning "risk assessment" and is matched by prefix in code.
COLUMN_SYNONYMS: dict[str, str] = {
    "sr. #": "sno", "sr #": "sno", "sr.#": "sno", "s.no": "sno", "sno": "sno", "#": "sno", "no": "sno",
    "task id": "id", "tfs/portal id": "id", "portal/tfs id": "id", "tfs id": "id", "portal id": "id", "id": "id",
    "module": "module",
    "new feature/ improvement of current feature": "feature_type",
    "prerequisites": "prerequisites",
    "details": "details", "description": "details",
    "configuration changes": "config_changes",
    "key feature": "key_feature", "key features": "key_feature",
    "is there a change to previous behavior?": "behavior_change",
    "is there a change to previous behaviour?": "behavior_change",
    "is this feature 'on' by default?": "on_by_default",
}
