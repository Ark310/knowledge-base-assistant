# KB Scraper v4 — Phase 2: Ticket Engine on the New Portal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Drive ticket scraping through the new `TradeDeskPortal` adapter end-to-end — login, per-ticket fields/comments, resolution, and real file downloads (comment + resolution) — with 1–10 parallel workers, Pause/Resume, a live Title/Files callback, and an operator-confirmed smoke test.

**Architecture:** A `RunControl` object (cancel + pause/resume gate) is shared by all engines. `ticket_engine.run_ticket_scrape` builds one `TradeDeskPortal` per worker (injectable for tests), logs in, and for each ticket assembles a full record via the Phase-1 parser, then opens the Resolve and Files sub-views to capture the resolution and download every file through the browser. `ticket_writer` persists the record (JSON + Markdown) referencing the downloaded files. The smoke test exercises the whole chain against the live portal.

**Tech Stack:** Python 3.12, Playwright sync (system Chrome), BeautifulSoup4, pytest. Test interpreter `scraper\venv\Scripts\python.exe`. Builds on Phase 1 (branch `feat/kb-scraper-v4`, last commit `589822f`).

## Global Constraints
- Headed Chrome only; rendered-DOM extraction only; **never** touch the encrypted API.
- Password: consumed by `portal.login()`; never stored beyond the worker call, never logged, never a shell arg.
- File bytes come through the browser (encrypted channel) — download by clicking "Download" and capturing Playwright's `download` event; never fetch a raw URL.
- On-disk output contract: `{output_dir}/ticket_{id}.json` + `.md`, attachments under `{output_dir}/attachments/{id}/`. `output_dir` defaults to `LIBRARY_BASE/"tickets"` (Settings wiring is Phase 3).
- Workers clamp to **1–10**.
- **Do not modify** `scraper/ticket_tab.py` (the GUI) — it is rewritten in Phase 4. Keep it importable: re-export `CancellationToken` as an alias of `RunControl`, and have `run_ticket_scrape` accept BOTH `control=` and the legacy `cancel=` kwarg.
- Phase-1 parser API (do not change it): `is_not_found(html, ticket_id="")`, `parse_ticket_detail(html, ticket_id, portal_url)->dict` (`{}` on not-found), `parse_resolution(html)->{"text","attachments":[{"label"}]}`. Adapter API: `login`, `open_ticket`, `open_subview(label)`, `download_all(dest_dir)->list[Path]`, `is_login_page(html)`, `ticket_url`.

---

### Task 1: `RunControl` (cancel + pause/resume)

**Files:** Create `scraper/control.py`; Test `tests/test_run_control.py`

**Interfaces:**
- Produces: `class RunControl` with `cancelled: bool` (property), `paused: bool` (property), `cancel()`, `pause()`, `resume()`, `wait_if_paused()` (blocks while paused, returns immediately if cancelled).

- [ ] **Step 1: Failing tests.**
```python
# tests/test_run_control.py
import sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.control import RunControl

def test_fresh_is_not_cancelled_or_paused():
    c = RunControl()
    assert c.cancelled is False and c.paused is False

def test_cancel_sets_flag():
    c = RunControl(); c.cancel()
    assert c.cancelled is True

def test_pause_then_resume_toggles_paused():
    c = RunControl(); c.pause()
    assert c.paused is True
    c.resume()
    assert c.paused is False

def test_wait_if_paused_returns_immediately_when_not_paused():
    c = RunControl()
    t0 = time.monotonic(); c.wait_if_paused(); assert time.monotonic() - t0 < 0.2

def test_wait_if_paused_unblocks_on_resume():
    c = RunControl(); c.pause()
    released = []
    def waiter():
        c.wait_if_paused(); released.append(True)
    th = threading.Thread(target=waiter); th.start()
    time.sleep(0.2); assert not released          # still blocked
    c.resume(); th.join(timeout=2); assert released  # unblocked

def test_wait_if_paused_returns_when_cancelled_even_if_paused():
    c = RunControl(); c.pause()
    released = []
    def waiter():
        c.wait_if_paused(); released.append(True)
    th = threading.Thread(target=waiter); th.start()
    time.sleep(0.2); c.cancel(); th.join(timeout=2)
    assert released
```
- [ ] **Step 2: Run — expect FAIL** (`scraper\venv\Scripts\python.exe -m pytest tests/test_run_control.py -v`).
- [ ] **Step 3: Implement.**
```python
# scraper/control.py
"""Run control shared by the scraper engines: cancel + pause/resume.

A single object lets the GUI stop a run (cancel) or hold it (pause) and continue
(resume). Workers call wait_if_paused() at item boundaries.
"""
from __future__ import annotations
import threading

class RunControl:
    def __init__(self) -> None:
        self._cancelled = False
        self._resume = threading.Event()
        self._resume.set()  # set == running; cleared == paused

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    def cancel(self) -> None:
        self._cancelled = True
        self._resume.set()  # wake any waiters so they observe the cancel

    def pause(self) -> None:
        if not self._cancelled:
            self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    def wait_if_paused(self) -> None:
        while not self._resume.is_set() and not self._cancelled:
            self._resume.wait(0.2)
```
- [ ] **Step 4: Run — expect PASS** (6 tests).
- [ ] **Step 5: Commit.** `git add scraper/control.py tests/test_run_control.py && git commit -m "feat(v4): RunControl (cancel + pause/resume gate)"`

---

### Task 2: `ticket_writer` for downloaded files

**Files:** Rewrite `scraper/writers/ticket_writer.py`; Test `tests/test_ticket_writer.py`

**Interfaces:**
- Consumes a ticket `data` dict: fields + `comments:[{id,author,date,internal,body,attachments:[{label,saved_path?}]}]` + `resolution:{text,attachments:[{label,saved_path?}]}` (optional) + `attachments:[{filename,saved_path}]` (ticket-level, optional) + `url`,`scraped_at`.
- Produces: `save_ticket(data: dict, tickets_base: Path) -> None` writing `ticket_{id}.json` (the dict verbatim) + `ticket_{id}.md`. **No base64 handling** (files are already downloaded by the adapter).

- [ ] **Step 1: Failing tests.**
```python
# tests/test_ticket_writer.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.writers.ticket_writer import save_ticket

def _data():
    return {
        "ticket_id": "76511", "title": "Org config", "product": "TD Client Server",
        "status": "18 - Internal CSQA UAT", "organization": "Northwind Trading",
        "url": "https://portal.contoso.example/tickets/76511/edit", "scraped_at": "2026-06-23T00:00:00",
        "comments": [
            {"id": "1", "author": "Jordan Lee", "date": "Jun 22, 2026 at 12:57 PM",
             "internal": True, "body": "Done.", "attachments": []},
            {"id": "2", "author": "Alex Kim", "date": "Jun 18, 2026 at 9:10 AM",
             "internal": False, "body": "See log.",
             "attachments": [{"label": "error-log.txt", "saved_path": "attachments/76511/error-log.txt"}]},
        ],
        "resolution": {"text": "Fixed via script.",
                       "attachments": [{"label": "resolution-script.sql", "saved_path": "attachments/76511/resolution-script.sql"}]},
        "attachments": [
            {"filename": "error-log.txt", "saved_path": "attachments/76511/error-log.txt"},
            {"filename": "resolution-script.sql", "saved_path": "attachments/76511/resolution-script.sql"},
        ],
    }

def test_writes_json_and_md(tmp_path):
    save_ticket(_data(), tmp_path)
    assert (tmp_path / "ticket_76511.json").exists()
    assert (tmp_path / "ticket_76511.md").exists()

def test_json_roundtrips(tmp_path):
    save_ticket(_data(), tmp_path)
    loaded = json.loads((tmp_path / "ticket_76511.json").read_text(encoding="utf-8"))
    assert loaded["ticket_id"] == "76511"
    assert loaded["resolution"]["text"] == "Fixed via script."

def test_md_has_resolution_text_and_files(tmp_path):
    save_ticket(_data(), tmp_path)
    md = (tmp_path / "ticket_76511.md").read_text(encoding="utf-8")
    assert "## Resolution" in md and "Fixed via script." in md
    assert "resolution-script.sql" in md      # resolution file referenced
    assert "error-log.txt" in md              # comment file referenced
    assert "## Comments" in md

def test_md_handles_missing_resolution(tmp_path):
    d = _data(); d.pop("resolution")
    save_ticket(d, tmp_path)
    md = (tmp_path / "ticket_76511.md").read_text(encoding="utf-8")
    assert "## Resolution" not in md
```
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** (`scraper/writers/ticket_writer.py`):
```python
"""Write scraped tradedesk ticket data to the tickets output dir as JSON + Markdown.
Files are already downloaded by the portal adapter; this module only references them.
"""
from __future__ import annotations
import json
from pathlib import Path

def save_ticket(data: dict, tickets_base: Path) -> None:
    tickets_base = Path(tickets_base)
    tickets_base.mkdir(parents=True, exist_ok=True)
    tid = data.get("ticket_id", "unknown")
    (tickets_base / f"ticket_{tid}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    (tickets_base / f"ticket_{tid}.md").write_text(_to_markdown(data), encoding="utf-8")

def _f(lines, label, value):
    if value:
        lines.append(f"**{label}:** {value}")

def _to_markdown(d: dict) -> str:
    tid = d.get("ticket_id", "?")
    lines = [f"# Ticket {tid}: {d.get('title','')}", ""]
    for label, key in (("Product","product"),("Organization","organization"),("Priority","priority"),
                       ("Category","category"),("Severity","severity"),("Status","status"),
                       ("Assignee","assignee"),("CSQA Owner","csqa_owner"),
                       ("Created By","created_by"),("Created At","created_at"),
                       ("Awaiting Production Deployment","awaiting_production_deployment")):
        _f(lines, label, d.get(key))
    _f(lines, "URL", d.get("url"))
    _f(lines, "Scraped At", d.get("scraped_at"))
    lines.append("")

    res = d.get("resolution")
    if res and (res.get("text") or res.get("attachments")):
        lines += ["## Resolution", "", res.get("text", ""), ""]
        for a in res.get("attachments") or []:
            sp = a.get("saved_path"); name = a.get("label") or (Path(sp).name if sp else "file")
            lines.append(f"- [{name}]({sp})" if sp else f"- {name}")
        lines.append("")

    comments = d.get("comments") or []
    if comments:
        lines += ["## Comments", ""]
        for c in comments:
            tag = " (internal)" if c.get("internal") else ""
            lines.append(f"### #{c.get('id','')} — {c.get('author','')} · {c.get('date','')}{tag}")
            lines.append("")
            if c.get("body"):
                lines.append(c["body"])
            for a in c.get("attachments") or []:
                sp = a.get("saved_path"); name = a.get("label") or (Path(sp).name if sp else "file")
                lines.append(f"- [{name}]({sp})" if sp else f"- {name}")
            lines.append("")

    files = d.get("attachments") or []
    if files:
        lines += ["## Files", ""]
        for a in files:
            sp = a.get("saved_path"); name = a.get("filename") or (Path(sp).name if sp else "file")
            lines.append(f"- [{name}]({sp})" if sp else f"- {name}")
        lines.append("")
    return "\n".join(lines)
```
- [ ] **Step 4: Run — expect PASS** (4 tests). Run full suite — no regressions.
- [ ] **Step 5: Commit.** `git add scraper/writers/ticket_writer.py tests/test_ticket_writer.py && git commit -m "feat(v4): ticket_writer for downloaded files + resolution dict"`

---

### Task 3: `ticket_engine` on `TradeDeskPortal`

**Files:** Rewrite `scraper/ticket_engine.py`; Modify `scraper/ticket_settings.py` (default portal URL); Test `tests/test_ticket_engine.py`

**Interfaces:**
- Consumes: `RunControl`; `TradeDeskPortal`; parser (`is_not_found`, `parse_ticket_detail`, `parse_resolution`); `save_ticket`.
- Produces:
  - `CancellationToken = RunControl` (alias, for the un-rewritten GUI import).
  - `parse_ticket_input(raw)->list[str]` (KEEP existing implementation unchanged).
  - `@dataclass TicketEngineCallbacks` with `on_log, on_progress, on_ticket, on_finished` (existing) **+ new** `on_ticket_meta: Callable[[str,str,int],None]` (tid, title, files_count), default no-op.
  - `run_ticket_scrape(portal_url, username, password, ticket_ids, force=False, control=None, cb=None, workers=1, output_dir=None, portal_factory=None, cancel=None) -> dict`. `control = control or cancel or RunControl()`. `workers = max(1, min(10, workers))`. `output_dir = Path(output_dir or TICKETS_DIR)`. `portal_factory(portal_url)->portal` (default builds a headed Browser + TradeDeskPortal); the engine closes `portal.b` in a finally.

- [ ] **Step 1: Failing tests** (FakePortal — no browser/network):
```python
# tests/test_ticket_engine.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.control import RunControl
from scraper import ticket_engine as te

FIX = Path(__file__).parent / "fixtures" / "tradedesk"
def fx(n): return (FIX / n).read_text(encoding="utf-8")

class FakeBrowser:
    def close(self): pass

class FakePortal:
    """Returns Phase-1 fixtures; 'download_all' writes stub files for any 'Files N>0' ticket."""
    def __init__(self, portal_url, found=True):
        self.base = portal_url.rstrip("/"); self.b = FakeBrowser(); self.found = found
        self.logged_in = False
    def login(self, u, p): self.logged_in = True; return True
    def is_login_page(self, html): return False
    def ticket_url(self, tid): return f"{self.base}/tickets/{tid}/edit"
    def open_ticket(self, tid):
        return fx("ticket_detail.html") if self.found else fx("not_found.html")
    def open_subview(self, label):
        return fx("resolution.html") if label.lower().startswith("resolve") else fx("files.html")
    def download_all(self, dest_dir):
        dest_dir = Path(dest_dir); dest_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for name in ("error-log.txt", "resolution-script.sql"):
            p = dest_dir / name; p.write_text("stub"); out.append(p)
        return out

def _cb(rec):
    return te.TicketEngineCallbacks(
        on_log=lambda l, m: None,
        on_progress=lambda i, n: rec.setdefault("progress", []).append((i, n)),
        on_ticket=lambda tid, st: rec.setdefault("tickets", []).append((tid, st)),
        on_ticket_meta=lambda tid, title, nfiles: rec.setdefault("meta", []).append((tid, title, nfiles)),
        on_finished=lambda rep: rec.update(report=rep),
    )

def test_workers_clamped_to_10():
    assert te._clamp_workers(99) == 10 and te._clamp_workers(0) == 1 and te._clamp_workers(4) == 4

def test_scrapes_ticket_with_resolution_and_files(tmp_path):
    rec = {}
    te.run_ticket_scrape("https://portal.contoso.example", "u", "p", ["76511"],
                         force=True, cb=_cb(rec), workers=1, output_dir=tmp_path,
                         portal_factory=lambda url: FakePortal(url))
    assert (tmp_path / "ticket_76511.json").exists()
    import json
    d = json.loads((tmp_path / "ticket_76511.json").read_text(encoding="utf-8"))
    assert d["resolution"]["text"]
    assert len(d["attachments"]) == 2
    assert rec["report"]["saved"] == 1
    assert ("76511", "ok") in rec["tickets"]
    assert rec["meta"] and rec["meta"][0][0] == "76511" and rec["meta"][0][2] == 2  # files count

def test_not_found_reported(tmp_path):
    rec = {}
    te.run_ticket_scrape("https://portal.contoso.example", "u", "p", ["999"],
                         force=True, cb=_cb(rec), workers=1, output_dir=tmp_path,
                         portal_factory=lambda url: FakePortal(url, found=False))
    assert rec["report"]["not_found"] == 1
    assert not (tmp_path / "ticket_999.json").exists()

def test_cancel_before_run_scrapes_nothing(tmp_path):
    rec = {}; ctrl = RunControl(); ctrl.cancel()
    te.run_ticket_scrape("https://portal.contoso.example", "u", "p", ["76511"],
                         force=True, cb=_cb(rec), workers=1, output_dir=tmp_path, control=ctrl,
                         portal_factory=lambda url: FakePortal(url))
    assert rec["report"]["saved"] == 0

def test_cancellationtoken_alias_is_runcontrol():
    assert te.CancellationToken is RunControl
```
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.** Rewrite `scraper/ticket_engine.py`. Keep `parse_ticket_input`, `_load_scraped`/`_mark_scraped` (state file `scraped_tickets.json`), `TICKETS_DIR`. Replace login/fetch with the adapter. Key pieces:
```python
from scraper.control import RunControl
from scraper.core import Browser
from scraper.portal.tradedesk_portal import TradeDeskPortal
from scraper.parsers.ticket_parser import is_not_found, parse_ticket_detail, parse_resolution
from scraper.writers.ticket_writer import save_ticket

CancellationToken = RunControl  # back-compat for the (Phase-4) GUI import
_SESSION_EXPIRED = object()
_SUBVIEW_RE = lambda label: re.compile(rf"{label}\s+(\d+)", re.I)

def _clamp_workers(n: int) -> int:
    return max(1, min(10, int(n or 1)))

def _subview_count(html: str, label: str) -> int:
    m = _SUBVIEW_RE(label).search(html or "")
    return int(m.group(1)) if m else 0

def _default_portal_factory(portal_url: str):
    b = Browser(headless=False, timeout_ms=30_000); b.open()
    return TradeDeskPortal(b, portal_url)

def _match_paths(items, by_name):
    for a in items or []:
        p = by_name.get(a.get("label"))
        if p:
            a["saved_path"] = str(p)

def _fetch_ticket(portal, tid, output_dir, cb):
    html = portal.open_ticket(tid)
    if portal.is_login_page(html):
        return _SESSION_EXPIRED
    if is_not_found(html, tid):
        return "not_found"
    data = parse_ticket_detail(html, tid, portal.base)
    if not data:
        return None
    if _subview_count(html, "Resolve") > 0:
        data["resolution"] = parse_resolution(portal.open_subview("Resolve"))
    saved = []
    if _subview_count(html, "Files") > 0:
        portal.open_subview("Files")
        saved = portal.download_all(Path(output_dir) / "attachments" / tid)
    data["attachments"] = [{"filename": p.name, "saved_path": str(p)} for p in saved]
    by_name = {p.name: p for p in saved}
    for c in data.get("comments") or []:
        _match_paths(c.get("attachments"), by_name)
    if isinstance(data.get("resolution"), dict):
        _match_paths(data["resolution"].get("attachments"), by_name)
    return data
```
The worker loop: build portal via factory; `if not portal.login(username, password): log+return`; for each tid → `control.wait_if_paused(); if control.cancelled: break`; increment progress under a lock; skip if `not force and tid in already_scraped`; `result=_fetch_ticket(...)`; on `_SESSION_EXPIRED` re-login once and retry; tally saved/not_found/failed; on success `save_ticket(result, output_dir)`, `_mark_scraped(tid)` under a lock, `cb.on_ticket(tid,"ok")`, `cb.on_ticket_meta(tid, result.get("title",""), len(result.get("attachments") or []))`. `finally: portal.b.close()`. Parallel path: round-robin `ticket_ids[i::workers]` threads, join all. End: `cb.on_finished(stats)`; return stats. Also set ticket_settings default portal URL → `https://portal.contoso.example`.
- [ ] **Step 4: Run — expect PASS** (engine tests). Run full suite — no regressions.
- [ ] **Step 5: Commit.** `git add scraper/ticket_engine.py scraper/ticket_settings.py tests/test_ticket_engine.py && git commit -m "feat(v4): ticket_engine on TradeDeskPortal (workers 1-10, pause, resolution+files)"`

---

### Task 4: Live Files-DOM validation + smoke test rewrite (CONTROLLER + OPERATOR — interactive)

This task needs the operator logged into the live portal; it is run by the controller in-session, not a background subagent.

**Files:** Possibly fix `scraper/parsers/ticket_parser.py` (`parse_files`) + `tests/fixtures/tradedesk/files.html` if the real Files DOM differs; Rewrite `scraper/smoke_test.py`

- [ ] **Step 1: Capture the REAL Files sub-view DOM** (operator logged in): open a ticket with ≥1 file, click Files, capture the rendered HTML structure (tags/classes only, no PII). Compare to the synthetic `files.html`.
- [ ] **Step 2: If the real DOM differs**, update `parse_files` (and refresh `files.html` to match real structure, PII-free) so real files are extracted; re-run `tests/test_tradedesk_ticket_parser.py`.
- [ ] **Step 3: Rewrite `scraper/smoke_test.py`** to run the full chain against the live portal: build a `TradeDeskPortal`, `login` (URL+username from `ticket_settings`, password from keyring), `run_ticket_scrape` for ONE ticket that has comments + a comment file + resolution + resolution file, into a temp dir; print a checklist of what was captured (fields present, N comments, comment file saved, resolution text present, resolution file saved). No password printed.
- [ ] **Step 4: Operator runs the smoke** (`scraper\venv\Scripts\python.exe scraper\smoke_test.py`) and confirms the saved JSON/MD + downloaded files look right.
- [ ] **Step 5: Commit** any parser/fixture fixes + the smoke test. `git commit -m "test(v4): live Files-DOM validation + portal smoke test"`

---

### Task 5: Phase 2 regression gate + final review

- [ ] **Step 1:** Full suite green: `scraper\venv\Scripts\python.exe -m pytest tests/ -q`.
- [ ] **Step 2:** Final whole-branch review of the Phase 2 diff (base = Phase-1 head `589822f`); fix Critical/Important, record Minor.
- [ ] **Step 3:** Update `.superpowers/sdd/progress.md` + memory; report Phase 2 complete and tee up Phase 3.

---

## Self-Review
- **Spec coverage:** RunControl/pause (Task 1), file persistence (Task 2), engine+workers+resolution+files+download+callback (Task 3), live Files validation + smoke (Task 4), gate (Task 5). Phase-1 carryover (Files-DOM, smoke, download-failure surfacing) → Task 4 + the engine's per-file tolerant `download_all`. ✅
- **Placeholders:** none — every code step carries full code; Task 4 is inherently interactive (live portal) and says exactly what to capture/confirm. ✅
- **Type consistency:** `on_ticket_meta(tid,title,files_count)` defined in Task 3 and asserted in its tests; `RunControl`/`CancellationToken` alias consistent; `parse_resolution`→dict matches the writer's `resolution.text`/`resolution.attachments` consumption in Task 2. ✅
