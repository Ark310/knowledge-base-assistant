# KB Scraper v4 — Phase 5: KB Tab (Option C) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the unusable 43-card KB grid with the approved **Option C master/detail** (families sidebar + per-family detail table), fold **Release Notes** into the KB tab, restore the v1/v2 actions (Validate / Rebuild Indexes / Scrape All / Force All / per-space scrape), add **Pause/Resume + Stop**, send KB output to the configured folder, and restructure the window to **two tabs (Tickets + Knowledge Base)**.

**Architecture:** The KB tab gets a left **families rail** (the 7 KB families from `KB_PRODUCT_GROUPS` + a **Release Notes** entry) and a right **detail table** of the selected family's spaces. KB families drive `KBEngine`; the Release Notes entry drives the v1 `Engine` (`config.PRODUCTS`). Both engines gain a Pause gate by switching their cancel token to the shared `RunControl` (Phase 2) and calling `wait_if_paused()` at scrape-loop boundaries; `KBEngine` takes an `output_base` (default `KB_LIBRARY_BASE`) so it can write to `app_settings.kb_dir()`. `MainWindow` drops the standalone v1 Release-Notes tab.

**Tech Stack:** PySide6, pytest. Test interpreter `scraper\venv\Scripts\python.exe`. Builds on Phase 4 (branch `feat/kb-scraper-v4`, head `25e0be4`). GUI tested **offscreen**. Layout reference: the approved Option-C mockup (artifact `3cf1cd5b…`).

## Global Constraints
- Two cancel systems exist: `scraper.engine.CancellationToken` (v1/v2 engines, `.is_cancelled()`) and `scraper.control.RunControl` (tickets, `.cancelled` + pause). Unify by adding `is_cancelled()` to `RunControl` and aliasing `scraper.engine.CancellationToken = RunControl` — so both engines accept the same object and gain `wait_if_paused()`.
- KB output defaults to the current location (`KB_LIBRARY_BASE` = `LIBRARY_BASE/"kb"`); the tab passes `app_settings.kb_dir()`. Release-Notes output stays `LIBRARY_BASE/{product}` (RN is not one of the two configurable per-type paths). Defaults keep behavior unchanged.
- Preserve the v1/v2 actions (Validate, Rebuild Indexes, Scrape All, Force All, per-space scrape + Force). Don't change scraping logic beyond the pause gate + output_base.
- GUI tested offscreen. Password/keyring untouched here (KB has no credentials).
- KB families come from `KB_PRODUCT_GROUPS` (7 families, 43 spaces); the Release-Notes detail lists `config.PRODUCTS` (TradeDesk/Web4/SalesHub).

---

### Task 1: KB/RN engine Pause gate + KB `output_base`

**Files:** Modify `scraper/control.py`, `scraper/engine.py`, `scraper/kb_engine.py`; Test `tests/test_engine_pause.py` (+ keep existing `tests/test_engine.py` green).

**Interfaces:**
- `RunControl.is_cancelled() -> bool` (alias of the `cancelled` property; back-compat for v1/KB engines).
- `scraper.engine.CancellationToken` IS `scraper.control.RunControl` (alias).
- `KBEngine(callbacks=None, cancel_token=None, output_base=None)` — `self.output_base = Path(output_base) if output_base else KB_LIBRARY_BASE`; all `KB_LIBRARY_BASE` uses become `self.output_base`.
- Both engines call `self.cancel.wait_if_paused()` immediately before each `if self.cancel.is_cancelled():` loop check.

- [ ] **Step 1: Failing tests.**
```python
# tests/test_engine_pause.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.control import RunControl
import scraper.engine as engine
import scraper.kb_engine as kb_engine

def test_runcontrol_is_cancelled_compat():
    c = RunControl()
    assert c.is_cancelled() is False
    c.cancel()
    assert c.is_cancelled() is True

def test_engine_cancellationtoken_is_runcontrol():
    assert engine.CancellationToken is RunControl

def test_kbengine_output_base_default_and_override(tmp_path):
    from scraper.kb_config import KB_LIBRARY_BASE
    assert kb_engine.KBEngine().output_base == KB_LIBRARY_BASE
    assert kb_engine.KBEngine(output_base=tmp_path / "kb").output_base == tmp_path / "kb"

def test_paused_runcontrol_then_cancel_releases():
    # wait_if_paused returns once cancelled even while paused (engines won't hang on close)
    import threading, time
    c = RunControl(); c.pause()
    released = []
    threading.Thread(target=lambda: (c.wait_if_paused(), released.append(1)), daemon=True).start()
    time.sleep(0.2); assert not released
    c.cancel(); time.sleep(0.3); assert released
```
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.**
  - `scraper/control.py`: add to `RunControl`:
    ```python
    def is_cancelled(self) -> bool:   # back-compat alias for the v1/KB engines
        return self._cancelled
    ```
  - `scraper/engine.py`: delete the local `class CancellationToken` (lines ~18-24) and replace with:
    ```python
    from scraper.control import RunControl
    CancellationToken = RunControl   # unified cancel + pause token
    ```
    In `scrape_all` (before `if self.cancel.is_cancelled():`) and in `_scrape_one`'s loop (before its `if self.cancel.is_cancelled():`), add `self.cancel.wait_if_paused()`.
  - `scraper/kb_engine.py`: `__init__` gains `output_base=None` → `self.output_base = Path(output_base) if output_base else KB_LIBRARY_BASE`. Replace the three `KB_LIBRARY_BASE` uses (`rebuild_indexes` → `generate_kb_index(self.output_base, KB_SPACES)`; `_scrape_one` `screenshot_dir` and `save_article(data, self.output_base, cfg)`) with `self.output_base`. Add `self.cancel.wait_if_paused()` before both `if self.cancel.is_cancelled():` checks (in `scrape_all` and `_scrape_one`). `CancellationToken` import is unchanged (now the RunControl alias).
- [ ] **Step 4: Run — expect PASS (4)** + `tests/test_engine.py` still green + full suite green.
- [ ] **Step 5: Commit.** `git add scraper/control.py scraper/engine.py scraper/kb_engine.py tests/test_engine_pause.py && git commit -m "feat(v4): Pause gate (RunControl) for KB/RN engines + KBEngine output_base"`

---

### Task 2: KB tab → Option C (families sidebar + detail table)

**Files:** Rewrite `scraper/kb_tab.py`; Test `tests/test_kb_tab.py`. Read first: the current `scraper/kb_tab.py` (worker/callback/bridge pattern to keep), `scraper/kb_engine.py` + `scraper/engine.py` (actions), `scraper/kb_config.py` (`KB_PRODUCT_GROUPS`), `scraper/config.py` (`PRODUCTS`), `scraper/app_settings.py` (`kb_dir`), `scraper/control.py` (`RunControl`). Layout = the approved Option-C mockup.

**Interfaces / required attributes (for tests):**
- `class KBTab(QWidget)` exposing: `self.rail` (family selector — a QListWidget) listing the 7 KB family labels + `"Release Notes"`; `self.detail` (QTableWidget, columns `["Space", "Found", "New", "Skip", "Fail", ""]`); top-bar buttons `self.btn_validate`, `self.btn_rebuild`, `self.btn_scrape_all`, `self.btn_force_all`, `self.btn_pause`, `self.btn_stop`; `self.inp_filter` (QLineEdit, filters rail/detail by space name); `self._control` (RunControl); a `shutdown()` method (cancel+join worker).
- Selecting a rail family repopulates `self.detail` with that family's spaces (KB family → its `KB_SPACES` entries; "Release Notes" → `config.PRODUCTS` entries). Expose `self._populate_detail(family_label)` and a helper `self._families` dict mapping label → list of {key, display_name, engine_kind} where `engine_kind` ∈ {"kb","rn"}.
- Worker dispatch: a `_Worker(engine, action, kwargs, control)` thread (like the current one) where `engine` is the `KBEngine` (KB families/spaces) or the v1 `Engine` (Release Notes). Both wired to the same bridge callbacks (log/status/progress/finished) and the same `self._control`. KB actions use `output_base=app_settings.kb_dir()` (pass it when constructing `KBEngine`).

- [ ] **Step 1: Failing offscreen tests.**
```python
# tests/test_kb_tab.py
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])
from scraper.kb_tab import KBTab
from scraper.kb_config import KB_PRODUCT_GROUPS

def test_rail_lists_families_plus_release_notes():
    t = KBTab()
    labels = [t.rail.item(i).text() for i in range(t.rail.count())]
    for fam in KB_PRODUCT_GROUPS:
        assert fam in labels
    assert "Release Notes" in labels

def test_detail_has_expected_columns():
    t = KBTab()
    headers = [t.detail.horizontalHeaderItem(i).text() for i in range(t.detail.columnCount())]
    assert headers[:5] == ["Space", "Found", "New", "Skip", "Fail"]

def test_selecting_family_populates_spaces():
    t = KBTab()
    fam = next(iter(KB_PRODUCT_GROUPS))
    t._populate_detail(fam)
    assert t.detail.rowCount() == len(KB_PRODUCT_GROUPS[fam])

def test_release_notes_family_lists_products():
    import scraper.config as config
    t = KBTab()
    t._populate_detail("Release Notes")
    assert t.detail.rowCount() == len(config.PRODUCTS)

def test_toolbar_and_pause_present():
    t = KBTab()
    for a in ("btn_validate", "btn_rebuild", "btn_scrape_all", "btn_force_all", "btn_pause", "btn_stop", "inp_filter"):
        assert getattr(t, a) is not None

def test_shutdown_no_worker_is_noop():
    KBTab().shutdown()
```
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Rewrite `scraper/kb_tab.py`** to Option C. Keep `_SignalBridge`/`_BridgeCallbacks`/`_Worker` (extend the worker to take a `control` RunControl + an `engine` instance, and to run `getattr(engine, action)(**kwargs)`). Build: a top action row (Validate, Rebuild Indexes, Scrape All, Force All — `btn_scrape_all` objectName "PrimaryButton" — plus Pause, Stop, and `inp_filter`); a horizontal split: left `self.rail` (QListWidget of family labels incl. "Release Notes"), right `self.detail` (QTableWidget 6 cols) + a family header row (Scrape family / Force family); a progress bar + log pane (keep). Selecting a rail row calls `_populate_detail(label)`; per-space row gets a Scrape button → `_scrape_space(key, force)`; `_families` maps each label to its spaces with `engine_kind`. Wire `Scrape All`→ run KB `scrape_all` then RN `scrape_all`; Validate/Rebuild → KBEngine (+ optionally RN). Pause toggles `self._control.pause()/resume()`; Stop `self._control.cancel()`. Construct `KBEngine(callbacks=..., cancel_token=self._control, output_base=app_settings.kb_dir())` and `Engine(callbacks=..., cancel_token=self._control)` for RN. `on_status(key, stats)` updates the matching detail row's Found/New/Skip/Fail cells (track key→row). Add `shutdown()` (cancel+join the worker). `inp_filter.textChanged` filters the detail rows by space name.
- [ ] **Step 4: Run — expect PASS (6)** + full suite green.
- [ ] **Step 5: Commit.** `git add scraper/kb_tab.py tests/test_kb_tab.py && git commit -m "feat(v4): KB tab Option C — families sidebar + detail, Release Notes folded in, Pause/Resume"`

---

### Task 3: `MainWindow` → two tabs + close-drain

**Files:** Modify `scraper/gui.py`; Test `tests/test_app_shell.py` (extend). Read first: current `scraper/gui.py` `MainWindow._build_ui`/`closeEvent`.

**Interfaces:** `MainWindow` shows exactly two tabs: `"Tickets"` and `"Knowledge Base"` (the standalone v1 "Release Notes" tab + its StatusCards/v1-Engine wiring are removed — Release Notes now lives inside the KB tab). `closeEvent` drains BOTH `self.ticket_tab.shutdown()` and `self.kb_tab.shutdown()` (and any still-running v1 worker if retained).

- [ ] **Step 1: Failing test (extend test_app_shell.py).**
```python
def test_mainwindow_has_two_tabs():
    from scraper.gui import MainWindow
    win = MainWindow()
    titles = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert titles == ["Tickets", "Knowledge Base"]
```
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3:** In `MainWindow._build_ui`, remove the v1 Release-Notes tab (the `_build_v1_widget` StatusCards page) and its toolbar/Engine wiring that's now dead; add the two tabs `self.ticket_tab` ("Tickets") and `self.kb_tab` ("Knowledge Base") in that order. Remove now-unused v1 plumbing (`self.engine`, `self.cards`, `_scrape_one`, the v1 buttons) if it's no longer referenced — but KEEP it if the KB tab's Release-Notes group still imports the v1 `Engine` (it constructs its own). Extend `closeEvent` to call `self.ticket_tab.shutdown()` and `self.kb_tab.shutdown()` (guard with `hasattr`). Keep the branded top bar + Settings button from Phase 3.
- [ ] **Step 4: Run — expect PASS** + full suite green.
- [ ] **Step 5: Commit.** `git add scraper/gui.py tests/test_app_shell.py && git commit -m "feat(v4): MainWindow two tabs (Tickets + Knowledge Base); close drains both"`

---

### Task 4: Phase 5 gate + offscreen UI shot + final review

- [ ] **Step 1:** Full suite green: `scraper\venv\Scripts\python.exe -m pytest tests/ -q`.
- [ ] **Step 2:** Offscreen screenshot of the Option-C KB tab (rail + detail populated for one family) via a throwaway `_p5_ui_shot.py` for the user to review.
- [ ] **Step 3:** Final whole-branch review of the Phase 5 diff (base = Phase-4 head `25e0be4`); fix Critical/Important, record Minor.
- [ ] **Step 4:** Update `.superpowers/sdd/progress.md` + memory; report Phase 5 complete + recommend Phase 6 (packaging + smoke-gated build).

---

## Self-Review
- **Spec coverage:** Option-C master/detail (Task 2), v1/v2 buttons restored (Task 2 top bar + per-space), Release Notes folded in (Task 2 rail + Task 3 two-tab), Pause/Resume (Task 1 gate + Task 2 buttons), KB output from Settings (Task 1 output_base + Task 2 wiring), KB compaction (the whole point). ✅
- **Placeholders:** Task 1 is concrete (exact edits); the GUI tasks define attributes + offscreen tests and reference the current file + the mockup. No vague steps. ✅
- **Type consistency:** `RunControl.is_cancelled()`/`wait_if_paused()`/`cancel()` used by both engines; `CancellationToken=RunControl` alias; `KBEngine(output_base=)` ↔ `app_settings.kb_dir()`; `KBTab.shutdown()` ↔ `MainWindow.closeEvent` (mirrors the Phase-4 `TicketTab.shutdown()` contract). ✅
- **Risk/known:** folding two engines into one tab is the heaviest coupling in v4; the worker dispatches by engine instance + action name (existing pattern). Live behavior (real scrape with Pause) is a Phase-6 / manual check; offscreen verifies structure + wiring.
