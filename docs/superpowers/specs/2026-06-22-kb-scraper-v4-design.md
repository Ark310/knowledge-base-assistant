# Design: Contoso KB Scraper v4

**Date:** 2026-06-22
**Status:** Draft for review
**Supersedes scraper UI/portal layer of:** v3.1 (2026-06-10)

---

## 1. Goal

Take the Contoso KB Scraper to **v4**: re-target the support/ticket portal to the rebuilt
`portal.contoso.example` site, adopt the chatbot's enterprise look (splash + themed UI),
ship a lighter/faster exe (open in < 1 min), compact the Knowledge Base view, raise the
parallel-worker ceiling to 10, add a Settings dialog (per-type output folders + portal
credentials), add Pause/Resume, and fix the long-standing bugs (empty live "Title" column,
missing comment/resolution file extraction, unusable/missing worker field, corrupted exe icon).

Everything must be **enterprise-grade**: tested, with a user-confirmed smoke run before any exe build.

---

## 2. Decisions locked (with the user, 2026-06-22)

| Topic | Decision |
|---|---|
| Tab structure | **Two tabs: Tickets + Knowledge Base** (v1 Release Notes folded into the KB tab) |
| New portal | `portal.contoso.example` is a **brand-new encrypted JS SPA** (see §4). Scrape via the **authenticated browser's rendered DOM** — do NOT replay or decrypt the API |
| Portal login | Plain **username + password** form (no SSO/MFA). Sign-In button is JS-gated until both fields are filled |
| KB layout | **Option C — sidebar / master-detail** (family rail + per-family detail table) |
| Pause | **Pause/Resume** available during both ticket and KB scraping (in addition to Stop) |
| Workers | **1–10** parallel browsers; control must be unmissable and work in the built exe |
| KB source | **Unchanged** — still `help.contoso.example` (Confluence). Only the ticket portal moved |
| App icon | **Ice scraper** `.ico` on the window and the exe |
| Output folders | Configurable per type in Settings; **defaults preserved** (`library/tickets`, `library/kb`) |
| Credentials | Move into Settings, collapsed/hidden until opened; URL+username on disk, password in OS keyring |
| Packaging | **One-folder** PyInstaller build (drop one-file) for fast startup; exclude bundled Chromium |
| Version | `APP_VERSION = "4.0"`, changelog continues |

---

## 3. Architecture overview

PySide6 `QMainWindow` with a branded top bar (à la chatbot `gui.setMenuWidget`) + a `QTabWidget`
holding two tabs. App-wide QSS theme ported from the chatbot's `gui.PALETTE` / `FONT_STACK`.

```
scraper/
  config.py            APP_VERSION=4.0; paths; KB products (unchanged source)
  theme.py        NEW  PALETTE, FONT_STACK, app_stylesheet(), asset loaders (ported from chatbot gui)
  app.py          NEW  main(): QApplication, animated splash, MainWindow(2 tabs), window icon
  gui.py          ->   thinned: MainWindow shell + tab hosting (v1 release-notes logic moves into KB tab)
  settings_dialog.py NEW  Settings dialog: output paths + portal credentials (collapsible)
  app_settings.py NEW  persisted app settings (output paths) in state/app_settings.json
  control.py      NEW  RunControl: unified cancel + pause/resume gate (shared by all engines)

  # Tickets
  ticket_tab.py        restyled; Workers 1-10; Pause/Resume; Title column fix; credentials read from Settings
  ticket_engine.py     workers cap ->10; pause gate; title/files in on_ticket; calls portal adapter
  portal/         NEW  pluggable portal adapter for the new SPA
    __init__.py
    tradedesk_portal.py  login + navigate + DOM extract + attachment download (the rebuild)
  parsers/ticket_parser.py  rewritten: parse the new rendered DOM (old aspx parser kept only for history)
  writers/ticket_writer.py  extended: real file attachments (comments + resolution)
  ticket_settings.py   credentials persistence (reused; portal_url default -> tradedesk)

  # Knowledge Base (Option C)
  kb_tab.py            redesigned: family sidebar + detail table; v1/v2 buttons; Release Notes group; Pause/Resume
  kb_engine.py         pause gate added (logic otherwise unchanged)
  engine.py            v1 release-notes engine reused, driven from the KB tab's "Release Notes" group
  kb_config.py         unchanged (43 spaces / 7 families)
  core.py              Browser wrapper reused; minor helpers for SPA readiness/wait
```

### Module boundaries
- **`portal/tradedesk_portal.py`** is the only place that knows the new site's URLs, selectors, and
  login flow. The engine calls a small interface: `login()`, `open_ticket(id)`, `extract_ticket()`,
  `extract_resolution()`, `download_attachments(dest)`. This isolates portal churn from the engine.
- **`control.py`** `RunControl` exposes `cancelled`, `paused`, `wait_if_paused()`, `cancel()`,
  `pause()`, `resume()`. Engines call `wait_if_paused()` at item boundaries; one object serves the
  ticket engine (threaded) and the KB/RN engines (single-threaded).
- **`theme.py`** is import-light (PySide6 only) so the splash can show before any heavy import.

---

## 4. New portal (portal.contoso.example) — findings & scraping model

Confirmed by live guided discovery on 2026-06-22 (logged in `.wolf/cerebrum.md`):

- **It is a modern JS SPA** ("SupportPortalClient"). The old `support.contoso.example` ASP.NET WebForms
  portal (`edit_bug.aspx`, `#user`/`#pw`, VIEWSTATE, server-rendered HTML) is **gone**. The entire
  v3.1 `ticket_parser.py` selector world is obsolete.
- **The API is end-to-end encrypted.** SPA host `portal.contoso.example` → API host
  `portal.contoso.example/api/...`. Both request params (`?payload=…`) and response bodies
  (`{"payload":"…"}`) are AES-GCM envelopes with anti-replay (nonce + timestamp + sessionId).
  **Conclusion: we do not touch the API.** Raw capture is ciphertext; replay is blocked; replicating
  the crypto is brittle and out of scope. We scrape the **rendered DOM** the SPA produces after it
  decrypts in-browser — i.e. exactly what an authorized user sees.

### Login flow (per worker browser)
1. `goto portal.contoso.example` → redirects to `/login?returnUrl=%2F`.
2. Fill `Username` + `Password` textboxes; the **Sign In button enables** once both are non-empty; click it.
3. Session readiness: authenticated app routes load (e.g. `/dashboard/dynamic`). Login screen
   detection = presence of the Username+Password sign-in form.
4. Password handling unchanged from v3.1 rules: keyring only, never on disk, never logged.

### Ticket extraction (rendered DOM)
- **Direct navigation:** `portal.contoso.example/tickets/{id}/edit`. Readiness signal: page `<title>`
  becomes `Ticket ID {id} - {org} - {title}` (we wait for the title/fields to render).
- **Header:** `Ticket # {id}`, title, `Created MM/DD/YYYY by {user}` + relative age.
- **Fields render as buttons** each `label* + value` — map: Organization, Project (→product),
  Priority, Category, Severity, Status, Assigned to, CSQA Owner, `Awaiting Production Deployment`
  checkbox, plus collapsible **"Show Estimation & Planning"** (expand to capture estimate/date fields).
- **Comments:** `Comments (N)`; each block = author + `comment {id} posted by {Author}` + optional
  `Internal` badge + date (`Mon DD, YYYY at H:MM AM/PM`) + body paragraphs. Comment files appear as
  **Download** buttons inside the block.
- **Resolution:** behind the `Resolve N` sub-view button. Extract resolution text + any file.
- **Files:** `Files N` sub-view aggregates all ticket attachments — used as the authoritative file list.
- **Not-found / no-access:** detect the SPA's empty/error state and report `not_found`.

> Exact selectors/refs are mapped in **Phase 1 (guided discovery)** against ticket #76511 — the
> brainstorm intentionally did not click mutating controls (`Update Ticket`, `Park`, `Post Comment`)
> on the live ticket. View sub-tabs (`Resolve`, `Files`) get verified there.

### Attachments (comments + resolution) — the v3.1 gap
Files come through the encrypted channel, so we cannot fetch a raw URL. Instead the engine **clicks
the Download button in the browser and captures Playwright's `download` event**, saving the real file
to `library/tickets/attachments/{ticket_id}/`. The `Files N` view enumerates everything; each comment's
inline Download and the resolution's file are captured the same way. JSON records
`{filename, saved_path, source: comment|resolution, comment_id?}` — raw bytes never round-trip through logs.

---

## 5. Ticket tab + engine changes

- **Workers 1–10.** `ticket_engine.run_ticket_scrape` cap `min(4,…) → min(10,…)`; round-robin chunking
  unchanged. Each worker = its own authenticated `Browser` (threading model from v3.1, which is sound).
- **Worker control is unmissable.** Replace the tiny `QSpinBox` with a labeled stepper component
  (blue "WORKERS" tag + − / value / + / "/ 10"), validated to render correctly in the **built exe**
  (the prior complaint). It sits on the primary action row, never collapsed.
- **Title column fix (bug).** Root cause: `on_ticket(tid, status)` carries no title and the tab inserts
  an empty cell. Fix: add a new `on_ticket_meta(tid, title, files_count)` callback (leaving the existing
  `on_ticket(tid, status)` intact for status updates); the engine already has the title at save time.
  The table's Title and new **Files** columns populate live as each ticket completes.
- **Pause/Resume.** New Pause button toggles to Resume. Engine workers call
  `control.wait_if_paused()` between tickets (finish the in-flight ticket, then block until Resume or
  Stop). Browsers stay open while paused; existing session-expiry re-login covers long pauses.
- **Credentials** are no longer entered on this tab — they're read from Settings (URL + username from
  disk, password from keyring). The tab shows a compact "signed in as … · Credentials in Settings" line
  and a friendly prompt if none are saved.
- Ticket-ID input (single / comma / range), Force, results table, and log pane are **kept** and restyled.

---

## 6. Knowledge Base tab (Option C) — compaction + folded Release Notes

Replaces the 43-card scroll grid with a **master/detail**:

- **Top action bar (the v1/v2 buttons, preserved):** `Validate`, `Rebuild Indexes`, `Scrape All`,
  `Force All`, a space **filter** box, plus **Pause/Resume** and **Stop**.
- **Left rail:** the 7 KB families + a **"Release Notes"** group (folds in v1). Each rail item shows its
  space count and updates with live rollups during a run.
- **Right detail:** compact table of the selected group's spaces — `Space | Found | New | Skip | Fail`
  + per-space `Scrape`/`Force`, and a header `Scrape family` / `Force family`.
- **Release Notes group** drives the existing v1 `engine.py` (TradeDesk / Web4 / SalesHub release-note
  tables from `help.contoso.example`, with `Validate` / `Discover` / `Rebuild Indexes`); KB families drive
  `kb_engine.py`. Both share the themed look and the `RunControl` pause gate.
- Output path label reflects the configurable KB output (default `library/kb`).

---

## 7. Settings dialog

Opened from the ⚙ button in the top bar. Modal `QDialog`, sectioned:

- **Output folders:** two folder pickers — *Tickets output* (default `library/tickets`) and
  *Knowledge Base output* (default `library/kb`). Persisted to `state/app_settings.json`. Defaults are
  the current locations, so existing behavior is unchanged until the user changes them. Engines read
  these instead of hardcoded `TICKETS_DIR` / `KB_LIBRARY_BASE`.
- **Portal credentials (collapsed by default):** Portal URL (default `https://portal.contoso.example`),
  Username, Password (masked). "Save" writes URL+username to `ticket_settings.json` and the password to
  the OS keyring. Hidden behind a "Show credentials" expander so it's out of the way until needed.
- Security rules unchanged: password keyring-only, never on disk, never logged, masked field.

---

## 8. UI / theme / splash / icon

- **Theme:** port the chatbot's `PALETTE` (brand blue `#51639e`, warm `#de9b6f`, light surfaces) +
  `FONT_STACK` (Segoe UI) into `scraper/theme.py`; apply app-wide QSS in `app.main()`. Primary buttons,
  status chips, tables, and the branded top bar all derive from it. (Mockup approved:
  artifact `3cf1cd5b-00ce-4d0f-94bc-b7bf66ead5d0`.)
- **Branded top bar** above the tab strip (`setMenuWidget`) with the Contoso mark, "KB Scraper", a
  `v4.0` pill, and the ⚙ Settings button.
- **Startup animation / splash:** branded `QSplashScreen` (logo on white canvas) with a subtle
  fade-in + an indeterminate "Starting…" shimmer while the window builds; `.finish(win)` on show.
  Keep it import-light so it appears immediately.
- **Icon:** rasterize an **ice-scraper** mark to a multi-size `.ico` (à la `_make_icon.py`); set as the
  `QMainWindow.setWindowIcon` and the PyInstaller `EXE(icon=…)` — fixes the "corrupted process logo".

---

## 9. Packaging (lighter + faster)

- **One-folder build** (PyInstaller `COLLECT`, like the chatbot) instead of one-file — eliminates the
  per-launch temp extraction that caused slow opens. Target: window visible in well under a minute.
- **Trim size:** we launch the user's installed Chrome via Playwright `channel="chrome"`, so the
  bundled Chromium/driver payload is unnecessary — exclude Playwright's browser binaries from the
  bundle (keep the Python `playwright` package). Validate Chrome-channel launch still works from the
  one-folder exe.
- **Lazy imports:** keep `gui`/`app`/`theme` top-level imports light (PySide6 + config + settings only);
  import Playwright/bs4/engine lazily inside workers/handlers so the splash and window appear fast.
- New `.spec` (`ContosoKBScraper-v4`): `icon=<ice-scraper.ico>`, one-folder, fresh `--workpath` to
  dodge the OneDrive `--clean` lock (known issue), re-copy any shipped assets after `COLLECT`.

---

## 10. Output formats

Unchanged on-disk contract (so the chatbot's ticket ingest keeps working):
`library/tickets/ticket_{id}.json` + `.md`, attachments under `library/tickets/attachments/{id}/`.
New: attachment records gain `source` (comment/resolution) and original `filename`; resolution files
are referenced from the `## Resolution` section of the Markdown. KB output unchanged.

---

## 11. QA / testing

- **Unit tests** (pytest, mirroring `Dev/kb_chatbot/tests` style):
  - `parsers/ticket_parser` against **saved HTML fixtures** of the new rendered ticket DOM (captured,
    PII-scrubbed, during Phase 1) — fields, comments, resolution, attachment references.
  - `ticket_input` parsing (kept), `RunControl` pause/cancel semantics, `app_settings` round-trip,
    output-path resolution, worker-cap clamp (1–10).
  - Title/files callback wiring (engine emits → tab populates).
- **Login/extraction are browser-driven**, so they're covered by the **smoke test**
  (`scraper/smoke_test.py` rewritten for the new portal): real login + one ticket end-to-end
  (fields + comments + a comment file + resolution + resolution file) saved to a temp dir.
- **Smoke-before-build is mandatory** (standing rule): no exe is built until the user confirms a
  successful smoke run. Then build one-folder, verify frozen boot + Chrome launch + window icon.
- Security gate: confirm no password/token is written to disk or logs at any verbosity.

---

## 12. Phased implementation outline (for the plan)

1. **Phase 1 — Guided portal discovery + adapter skeleton.** With the user logged in, map exact
   selectors for login, fields, comments, resolution, files; capture PII-scrubbed HTML fixtures;
   build `portal/tradedesk_portal.py` + rewrite `ticket_parser.py` against fixtures (TDD).
2. **Phase 2 — Ticket engine.** Workers→10, `RunControl` pause/cancel, attachment download via browser,
   title/files callbacks; smoke test rewrite.
3. **Phase 3 — Theme + app shell.** `theme.py`, `app.py`, branded top bar, splash, ice-scraper icon,
   Settings dialog + `app_settings.py`; wire output paths + credentials.
4. **Phase 4 — Tickets tab restyle.** Workers control, Pause/Resume, Title/Files columns, credentials-from-Settings.
5. **Phase 5 — KB tab (Option C).** Sidebar/detail, v1/v2 buttons, Release Notes group, Pause/Resume.
6. **Phase 6 — Packaging + QA.** One-folder `.spec`, Chromium-exclude, version bump 4.0, full test pass,
   user-confirmed smoke, build + frozen-boot verification.

---

## 13. Risks / open items

- **SPA timing/fragility:** rendered-DOM scraping depends on the SPA finishing render. Mitigate with
  explicit readiness waits (title + key elements) and the existing retry/auto-restart logic.
- **View sub-tabs unverified:** `Resolve`/`Files` interaction is mapped in Phase 1; if a file lives only
  behind a click that triggers a download dialog, Playwright download capture handles it.
- **Session expiry during long pause:** covered by existing re-login on session-expired detection.
- **Chromium-exclude:** must verify the system-Chrome channel launches from the trimmed one-folder exe
  on a clean machine; if not, fall back to bundling the driver only.

## 14. Out of scope (YAGNI)
- No API/crypto reverse-engineering. No headless mode (headed is required for the portal, per v3.1
  decision). No change to the chatbot. No change to KB source or KB output schema. No combined
  "scrape tickets + KB in one click" run (the two tabs run independently).
