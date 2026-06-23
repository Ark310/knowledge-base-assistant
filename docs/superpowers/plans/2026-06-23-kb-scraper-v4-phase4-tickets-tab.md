# KB Scraper v4 — Phase 4: Tickets Tab Restyle & Behaviors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Rework the Tickets tab to the v4 look and wire the behaviors the user flagged: an **unmissable Workers 1–10** control, **Pause/Resume** (+ Stop), the **Title and Files columns that fill in live**, credentials read from **Settings** (no inline entry), and the per-type **output folder** from app_settings.

**Architecture:** `scraper/ticket_tab.py` is rewritten. It drops its own credentials box (now in the Settings dialog), reads portal URL/username from `ticket_settings` + password from the OS keyring at run time, and passes a `RunControl` to `run_ticket_scrape` (control.pause()/resume()/cancel() driven by Pause/Stop buttons). The engine's `on_ticket_meta(tid, title, files_count)` callback is surfaced as a new Qt signal that populates the table's Title + Files columns. Output goes to `app_settings.tickets_dir()`.

**Tech Stack:** PySide6, pytest. Test interpreter `scraper\venv\Scripts\python.exe`. Builds on Phase 3 (branch `feat/kb-scraper-v4`, head `36476d5`). GUI tested **offscreen** (`QT_QPA_PLATFORM=offscreen`).

## Global Constraints
- Theme comes from the app stylesheet (Phase 3 `theme.app_stylesheet`, applied in `app.main()`). The tab must NOT set fighting inline styles; the **Start** button uses `setObjectName("PrimaryButton")` to pick up brand blue. Remove the old inline green button QSS.
- Password: never entered or stored in this tab — read from `ticket_settings.load_password(username)` (keyring) at run time; never logged. If missing, prompt the user to open Settings.
- Workers: `QSpinBox` range **1–10**, default **4** (the user liked 4 parallel workers), placed in a **prominent, always-visible** labelled row (the prior bug was the control being cramped/cut off) — a clear `Workers (1–10):` label + a readable spinbox, not a 52px box wedged into a button row.
- Engine call uses `control=` (a `RunControl`) and `output_dir=app_settings.tickets_dir()`. Do NOT change the engine/adapter/parser.
- Do NOT touch other tabs/modules. Only `scraper/ticket_tab.py` (+ its test). The KB tab is Phase 5.

---

### Task 1: Rewrite `ticket_tab.py`

**Files:** Rewrite `scraper/ticket_tab.py`; Test `tests/test_ticket_tab.py`. Read first: the current `scraper/ticket_tab.py` (structure to preserve: ticket-ID input + parse count + Force, results table, log pane, worker thread), `scraper/ticket_engine.py` (`run_ticket_scrape`, `TicketEngineCallbacks` incl. `on_ticket_meta`, `RunControl`/`CancellationToken`), `scraper/settings_dialog.py` (`SettingsDialog`), `scraper/app_settings.py` (`tickets_dir`), `scraper/ticket_settings.py` (`load`, `load_password`).

**Interfaces / required widget attributes (relied on by tests):**
- `class TicketTab(QWidget)` exposing: `self.spn_workers` (QSpinBox, min 1 / max 10 / value 4), `self.btn_start` (objectName "PrimaryButton"), `self.btn_pause` (QPushButton, toggles Pause↔Resume), `self.btn_stop`, `self.btn_settings` (opens `SettingsDialog`), `self.inp_tickets` (QLineEdit), `self.chk_force` (QCheckBox), `self.table` (QTableWidget), `self.lbl_creds` (QLabel status line). NO password/username/URL QLineEdits in this tab.
- Table: **4 columns** with headers `["Ticket #", "Status", "Title", "Files"]`.
- A slot `self._on_ticket_meta(tid: str, title: str, files: int)` that sets the Title cell (col 2) and Files cell (col 3) for that ticket's row.
- A `RunControl` held as `self._control`; Pause toggles `self._control.pause()`/`resume()` + button label; Stop calls `self._control.cancel()`.

- [ ] **Step 1: Failing offscreen tests.**
```python
# tests/test_ticket_tab.py
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QTableWidgetItem
_app = QApplication.instance() or QApplication([])
from scraper.ticket_tab import TicketTab

def test_workers_spinbox_1_to_10_default_4():
    t = TicketTab()
    assert t.spn_workers.minimum() == 1
    assert t.spn_workers.maximum() == 10
    assert t.spn_workers.value() == 4

def test_has_pause_and_settings_buttons():
    t = TicketTab()
    assert t.btn_pause is not None and t.btn_settings is not None
    assert t.btn_start.objectName() == "PrimaryButton"

def test_table_has_title_and_files_columns():
    t = TicketTab()
    headers = [t.table.horizontalHeaderItem(i).text() for i in range(t.table.columnCount())]
    assert headers == ["Ticket #", "Status", "Title", "Files"]

def test_no_inline_credential_fields():
    t = TicketTab()
    for attr in ("inp_pass", "inp_user", "inp_url"):
        assert not hasattr(t, attr), f"{attr} must move to Settings"
    assert hasattr(t, "lbl_creds")

def test_on_ticket_meta_populates_title_and_files():
    t = TicketTab()
    # seed a row for ticket 76511 (mirror how _start builds rows)
    t.table.setRowCount(0)
    t.table.insertRow(0)
    t.table.setItem(0, 0, QTableWidgetItem("#76511"))
    t._ticket_rows = {"76511": 0}
    t._on_ticket_meta("76511", "APA ONE - Org config", 2)
    assert t.table.item(0, 2).text() == "APA ONE - Org config"
    assert t.table.item(0, 3).text() == "2"
```
- [ ] **Step 2: Run — expect FAIL.** `scraper\venv\Scripts\python.exe -m pytest tests/test_ticket_tab.py -v`
- [ ] **Step 3: Rewrite `scraper/ticket_tab.py`.** Keep the worker-thread pattern but:
  - **Signals:** add `meta_sig = Signal(str, str, int)` to `_TicketSignals`; in `_TicketWorker.run`, build `TicketEngineCallbacks(..., on_ticket_meta=lambda tid, title, n: self.signals.meta_sig.emit(tid, title, n))`; call `run_ticket_scrape(..., control=self._control, workers=self._workers, output_dir=self._output_dir)`. Pass `self._control` (a `RunControl`) and `self._output_dir` into the worker ctor.
  - **Credentials:** remove the credentials `QGroupBox`. Add `self.lbl_creds` showing `Portal: {url} · signed in as {username}` (from `ticket_settings.load()`), or `Portal credentials not configured — open Settings` when username is blank; refresh it after the Settings dialog closes. Add `self.btn_settings` ("⚙ Settings") that does `SettingsDialog(self).exec()` then refreshes `lbl_creds`.
  - **Workers:** a prominent row: `QLabel("Workers (1–10):")` (bold) + `self.spn_workers = QSpinBox()` with `setRange(1, 10)`, `setValue(4)`, a readable min width (~64px). Not crammed into the Start/Stop row — give it its own clearly-visible line or generous spacing.
  - **Controls:** `self.btn_start` (objectName "PrimaryButton") → `_start`; `self.btn_pause` (disabled until running) → `_toggle_pause`; `self.btn_stop` (disabled until running) → `_stop`.
  - **Table:** `QTableWidget(0, 4)` with headers `["Ticket #", "Status", "Title", "Files"]`; `setStretchLastSection` off, set the Title column to stretch.
  - **`_start`:** read `url`/`username` from `ticket_settings.load()`, `password = ticket_settings.load_password(username)`. If `not (url and username and password)`: `QMessageBox.information(... "Configure portal credentials in Settings")`, open `SettingsDialog`, refresh, and return. Else build rows (Ticket # / Status=Queued / Title="" / Files=""), `self._control = RunControl()`, start the worker with `output_dir=app_settings.tickets_dir()`, set running state (enable Pause/Stop, disable Start/Settings/workers).
  - **`_toggle_pause`:** if `self._control.paused`: `resume()`, button text "⏸ Pause"; else `pause()`, button text "▶ Resume". Log the state.
  - **`_on_ticket_meta(tid, title, files)`:** look up `self._ticket_rows[tid]`, set col 2 = title, col 3 = str(files).
  - Keep `_on_ticket_done` (status col 1), `_on_progress`, `_emit_log`, `_on_finished`, `_set_running` (now also toggles Pause). Remove the inline green Start QSS (theme handles it).
  - Password is never logged; the worker clears it after use (keep the existing `finally: self._password = ""`).
- [ ] **Step 4: Run — expect PASS (5).** Full suite — no regressions.
- [ ] **Step 5: Commit.** `git add scraper/ticket_tab.py tests/test_ticket_tab.py && git commit -m "feat(v4): Tickets tab restyle — workers 1-10, pause/resume, live Title/Files, creds from Settings"`

---

### Task 2: Gate + offscreen UI shot + final review

- [ ] **Step 1:** Full suite green: `scraper\venv\Scripts\python.exe -m pytest tests/ -q`.
- [ ] **Step 2:** Offscreen screenshot of the restyled Tickets tab (throwaway `_p4_ui_shot.py`, `QT_QPA_PLATFORM=offscreen`, build TicketTab inside a QMainWindow with the app stylesheet, `grab().save(png)`) for the user to review — confirm the Workers control is prominent and the Title/Files columns are present.
- [ ] **Step 3:** Final whole-branch review of the Phase 4 diff (base = Phase-3 head `36476d5`); fix Critical/Important, record Minor.
- [ ] **Step 4:** Update `.superpowers/sdd/progress.md` + memory; report Phase 4 complete + recommend Phase 5 (KB tab, Option C).

---

## Self-Review
- **Spec coverage:** unmissable Workers 1–10 (Task 1, dedicated row + test), Pause/Resume + Stop (RunControl wiring + test), live Title/Files columns (on_ticket_meta signal + test), credentials from Settings + no inline entry (status line + test), output_dir from app_settings. All from the v4 spec §5. ✅
- **Placeholders:** the rewrite references the current file + concrete interfaces + offscreen tests; behaviors specified step-by-step. GUI code is written by the implementer against the named attributes/tests (Qt construction). No vague steps. ✅
- **Type consistency:** `meta_sig(str,str,int)` ↔ engine `on_ticket_meta(tid,title,files_count)`; `RunControl.pause/resume/cancel/paused` ↔ Phase-2 control.py; `app_settings.tickets_dir()`, `SettingsDialog`, `ticket_settings.load`/`load_password` all match prior phases. ✅
- **Live-visual:** offscreen verifies structure; the user should run `scraper\app.py` → Tickets tab to confirm the Workers control reads clearly and Title/Files fill during a real scrape.
