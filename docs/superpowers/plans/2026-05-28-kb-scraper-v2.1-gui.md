# V2.1 GUI Desktop App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan task-by-task.

**Goal:** Replace the broken Launch.bat with a PySide6 desktop application packaged as a single Windows executable (`ContosoKBScraper.exe`), giving full visibility (live log stream), real-time monitoring (status cards + progress bar), and graceful Stop control over scraper runs.

**Architecture:** Extract `run.py`'s orchestration into a callable `Engine` class with callbacks + a cancellation token. Build a PySide6 main window that runs the engine in a QThread, displaying logs/status/progress via Qt signals. Package via PyInstaller (`--onefile --windowed`, system Chrome via `channel="chrome"`).

**Tech Stack:** Python 3.10+, PySide6, PyInstaller, Playwright (already installed). No-git environment — no commit steps.

**Spec:** `docs/superpowers/specs/2026-05-28-kb-scraper-v2.1-gui.md`

All commands assume CWD is the Knowledge Base root. Python is `scraper\venv\Scripts\python.exe`.

---

## Task A: Engine refactor + run.py rewrite

**Files:**
- Create: `scraper/engine.py`
- Create: `tests/test_engine.py`
- Rewrite: `scraper/run.py`

The engine code, tests, and rewritten `run.py` for this task are given in **APPENDIX A** at the bottom of this plan, marked with section anchors. Subagents implementing this task: open the appendix and copy each block verbatim.

- [ ] **Step 1:** Write `tests/test_engine.py` using the content from APPENDIX A — `tests/test_engine.py`.
- [ ] **Step 2:** Run pytest; expect FAIL (module not found).
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest tests/test_engine.py -v 2>&1 | Select-Object -First 15
  ```
- [ ] **Step 3:** Create `scraper/engine.py` using the content from APPENDIX A — `scraper/engine.py`.
- [ ] **Step 4:** Run pytest; expect PASS (4 tests).
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest tests/test_engine.py -v
  ```
- [ ] **Step 5:** Rewrite `scraper/run.py` using the content from APPENDIX A — `scraper/run.py`.
- [ ] **Step 6:** Verify CLI:
  ```powershell
  scraper\venv\Scripts\python.exe scraper\run.py --help
  scraper\venv\Scripts\python.exe scraper\run.py --validate
  ```
  Expected: validate prints `117 / 18 / 21 versions`, `Validation PASSED`, exit 0.
- [ ] **Step 7:** Full test suite stays green:
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest tests/ -v
  ```
  Expected: 50 green (46 V2 + 4 new engine tests).

---

## Task B: PySide6 GUI (`scraper/gui.py`)

**Files:**
- Create: `scraper/gui.py`
- Modify: `scraper/requirements.txt` (append PySide6)

- [ ] **Step 1:** Install PySide6 in the venv:
  ```powershell
  scraper\venv\Scripts\python.exe -m pip install "PySide6>=6.6.0"
  ```
- [ ] **Step 2:** Append `PySide6>=6.6.0` to `scraper/requirements.txt` so it reads:
  ```
  playwright>=1.40.0
  beautifulsoup4>=4.12.0
  lxml>=4.9.0
  pytest>=7.4.0
  PySide6>=6.6.0
  ```
- [ ] **Step 3:** Create `scraper/gui.py` using the content from APPENDIX B at the bottom of this plan.
- [ ] **Step 4:** Smoke-test the GUI module imports (no QApplication launch):
  ```powershell
  scraper\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from scraper.gui import MainWindow; print('gui imports OK')"
  ```
  Expected: `gui imports OK`.

---

## Task C: Freeze-aware paths + PyInstaller build

**Files:**
- Modify: `scraper/config.py` (path block at top)
- Create: `ContosoKBScraper.spec`
- Create: `build_exe.bat`

- [ ] **Step 1:** Replace the top path block of `scraper/config.py` (everything from the first `from pathlib` line through the `REPORT_FILE` line — but NOT the `BASE_URL` / `PRODUCTS` / `COLUMN_SYNONYMS` sections below) with:

  ```python
  from pathlib import Path
  import sys

  # ── Paths ─────────────────────────────────────────────────────────────────────
  # When frozen as a PyInstaller exe, __file__ points inside a temp extract dir;
  # library/state must sit next to the executable instead.
  if getattr(sys, "frozen", False):
      BASE_DIR = Path(sys.executable).parent
      STATE_DIR = BASE_DIR / "state"
  else:
      BASE_DIR = Path(__file__).parent.parent           # Knowledge Base/
      STATE_DIR = Path(__file__).parent / "state"
  LIBRARY_BASE = BASE_DIR / "library"
  STATE_FILE   = STATE_DIR / "scraped_versions.json"
  LOG_FILE     = STATE_DIR / "run.log"
  REPORT_FILE  = STATE_DIR / "last_run_report.json"
  ```
- [ ] **Step 2:** Verify paths resolve when running from source:
  ```powershell
  scraper\venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'.'); from scraper.config import BASE_DIR, LIBRARY_BASE, STATE_FILE; print('BASE_DIR', BASE_DIR); print('LIBRARY', LIBRARY_BASE); print('STATE', STATE_FILE)"
  ```
  Expected: `BASE_DIR` ends with `Knowledge Base`; `STATE` ends with `state\scraped_versions.json`.
- [ ] **Step 3:** Full test suite stays green:
  ```powershell
  scraper\venv\Scripts\python.exe -m pytest tests/ -v
  ```
- [ ] **Step 4:** Install PyInstaller:
  ```powershell
  scraper\venv\Scripts\python.exe -m pip install "pyinstaller>=6.0"
  ```
- [ ] **Step 5:** Create `ContosoKBScraper.spec` using the content from APPENDIX C.
- [ ] **Step 6:** Create `build_exe.bat` using the content from APPENDIX C.
- [ ] **Step 7:** Build:
  ```powershell
  .\build_exe.bat
  ```
  Takes several minutes. Expected final lines: `Build complete. Artifact: dist\ContosoKBScraper.exe`.
- [ ] **Step 8:** Verify the artifact exists:
  ```powershell
  Get-Item dist\ContosoKBScraper.exe | Select-Object Name, Length
  ```
  Expected: size in the 80–150 MB range.

---

## Task D: Smoke-test the exe + cleanup

- [ ] **Step 1:** Delete the broken `Launch.bat`:
  ```powershell
  Remove-Item scraper\Launch.bat -Force
  ```
- [ ] **Step 2:** USER STEP — double-click `dist\ContosoKBScraper.exe`. Window must appear and stay open showing toolbar, three product cards, log pane.
- [ ] **Step 3:** USER STEP — click **Validate**. Log streams `117 / 18 / 21 versions`, then `Validation PASSED`.
- [ ] **Step 4:** USER STEP — click **Scrape** on the SalesHub card (Force unchecked). Chrome opens; progress bar advances `1/21 … 21/21`; SalesHub card shows `New: 21, Skipped: 0, Failed: 0` when done.
- [ ] **Step 5:** Verify outputs on disk:
  ```powershell
  Get-ChildItem library\saleshub\versions\*.json | Measure-Object | Select-Object Count
  Get-ChildItem library\saleshub\versions\*.md   | Measure-Object | Select-Object Count
  Get-ChildItem library\saleshub\versions\screenshots\*.png | Measure-Object | Select-Object Count
  Get-Content scraper\state\last_run_report.json
  ```
- [ ] **Step 6:** USER STEP — click **Force re-scrape ALL**, wait for a few pages, click **⏹ STOP**. Log shows cancel-acknowledged; window stays open.

---

## Quick Reference

| Goal | Action |
|------|--------|
| Run the app | Double-click `dist\ContosoKBScraper.exe` |
| Build the exe | Double-click `build_exe.bat` |
| Run from source (no build) | `scraper\venv\Scripts\python.exe scraper\gui.py` |
| Run from CLI | `scraper\venv\Scripts\python.exe scraper\run.py --all` |
| Run tests | `scraper\venv\Scripts\python.exe -m pytest tests/ -v` |

---

# Appendices (code blocks for subagents)

The appendices below contain the exact file contents referenced from Tasks A, B, and C. They live at the bottom of this plan so the task list reads clean. Subagents implementing each task must reproduce these character-for-character.

## APPENDIX A — Task A files

### `tests/test_engine.py`

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.engine import Engine, EngineCallbacks, CancellationToken


class RecordingCallbacks(EngineCallbacks):
    def __init__(self):
        self.logs = []
        self.statuses = []
        self.progress = []
        self.started = []
        self.finished = []
    def on_log(self, level, msg): self.logs.append((level, msg))
    def on_status(self, product, stats): self.statuses.append((product, dict(stats)))
    def on_progress(self, product, version, idx, total): self.progress.append((product, version, idx, total))
    def on_started(self, action): self.started.append(action)
    def on_finished(self, action, report): self.finished.append((action, report))


def test_cancel_token_default():
    t = CancellationToken()
    assert t.is_cancelled() is False
    t.cancel()
    assert t.is_cancelled() is True


def test_default_callbacks_are_no_ops():
    c = EngineCallbacks()
    c.on_log("info", "x"); c.on_status("p", {}); c.on_progress("p", "1.0", 0, 1)
    c.on_started("a"); c.on_finished("a", {})


def test_engine_validate_emits_status_for_each_product(monkeypatch):
    cb = RecordingCallbacks()
    eng = Engine(callbacks=cb, cancel_token=CancellationToken())

    from scraper import engine as eng_mod
    def fake_discover(space_key, http_get=None):
        return [{"version": "1.0", "title": "Version 1.0.0", "url": "http://x", "page_id": "1"}]
    monkeypatch.setattr(eng_mod, "discover_versions", fake_discover)

    ok = eng.validate()
    assert ok is True
    products_logged = [m for lvl, m in cb.logs if "versions" in m]
    assert len(products_logged) >= 3


def test_scrape_product_respects_cancel(monkeypatch):
    cb = RecordingCallbacks()
    tok = CancellationToken()
    eng = Engine(callbacks=cb, cancel_token=tok)

    from scraper import engine as eng_mod
    fake_versions = [{"version": f"v{i}", "title": f"V{i}", "url": f"http://x/{i}", "page_id": str(i)} for i in range(5)]
    monkeypatch.setattr(eng_mod, "discover_versions", lambda key, http_get=None: fake_versions)

    class FakeBrowser:
        def __init__(self, *a, **k): self.calls = 0
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def navigate(self, url): self.calls += 1
        def expand_confluence_macros(self): pass
        def screenshot(self, path): pass
        def get_content(self): return "<html><body></body></html>"
    fake_browser_instance = FakeBrowser()
    monkeypatch.setattr(eng_mod, "Browser", lambda *a, **k: fake_browser_instance)

    tok.cancel()
    stats = eng.scrape_product("saleshub", force=True)
    assert stats["new"] == 0
    assert fake_browser_instance.calls == 0
```

### `scraper/engine.py`

```python
"""V2.1 engine: orchestration with callbacks + cancellation. Shared by CLI and GUI."""
from __future__ import annotations
import json
import logging
from pathlib import Path

from scraper.config import (PRODUCTS, LIBRARY_BASE, STATE_FILE, REPORT_FILE, BASE_URL, COLUMN_SYNONYMS)
from scraper.core import Browser, StateTracker
from scraper.discovery import discover_versions
from scraper.parsers.universal import parse_page
from scraper.writers import json_writer, md_writer, index_generator
from scraper.config_writer import update_release_notes_urls
from scraper import config as config_module

log = logging.getLogger("scraper")


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False
    def cancel(self) -> None:
        self._cancelled = True
    def is_cancelled(self) -> bool:
        return self._cancelled


class EngineCallbacks:
    """No-op base; subclass and override to receive events."""
    def on_log(self, level: str, msg: str) -> None: pass
    def on_status(self, product: str, stats: dict) -> None: pass
    def on_progress(self, product: str, version: str, idx: int, total: int) -> None: pass
    def on_started(self, action: str) -> None: pass
    def on_finished(self, action: str, report: dict) -> None: pass


class LoggingCallbacks(EngineCallbacks):
    """Default CLI callbacks: route everything to the 'scraper' logger."""
    def on_log(self, level, msg):
        getattr(log, level if level in ("debug","info","warning","error","critical") else "info")(msg)
    def on_status(self, product, stats):
        log.info("%s status: %s", product, {k: v for k, v in stats.items() if k != "failed_urls"})
    def on_progress(self, product, version, idx, total):
        pass


class Engine:
    def __init__(self, callbacks: EngineCallbacks | None = None,
                 cancel_token: CancellationToken | None = None):
        self.cb = callbacks or EngineCallbacks()
        self.cancel = cancel_token or CancellationToken()

    def validate(self) -> bool:
        self.cb.on_started("validate")
        self.cb.on_log("info", "Validating space keys (dry-run, no scraping)...")
        ok = True
        report: dict = {}
        for key, cfg in PRODUCTS.items():
            try:
                items = discover_versions(cfg["space_key"])
                count = len(items)
                self.cb.on_log("info", f"  {key} [{cfg['space_key']}]: {count} versions")
                report[key] = {"space_key": cfg["space_key"], "count": count}
                if not items:
                    ok = False
            except Exception as exc:
                ok = False
                self.cb.on_log("error", f"  {key} [{cfg['space_key']}]: ERROR {exc}")
                report[key] = {"space_key": cfg["space_key"], "error": str(exc)}
        self.cb.on_log("info", f"Validation {'PASSED' if ok else 'FAILED'}")
        self.cb.on_finished("validate", report)
        return ok

    def discover_and_update_config(self) -> dict:
        self.cb.on_started("discover")
        self.cb.on_log("info", "Re-deriving release_notes_url for each product...")
        resolved: dict = {}
        for key, cfg in PRODUCTS.items():
            try:
                items = discover_versions(cfg["space_key"])
            except Exception as exc:
                self.cb.on_log("error", f"  {key}: discovery failed: {exc}")
                continue
            if items:
                resolved[key] = f"{BASE_URL}/display/{cfg['space_key']}"
                self.cb.on_log("info", f"  {key}: {len(items)} versions -> {resolved[key]}")
            else:
                self.cb.on_log("warning", f"  {key}: no versions found; leaving config unchanged")
        if resolved:
            config_path = Path(config_module.__file__)
            update_release_notes_urls(config_path, resolved)
            import importlib
            importlib.reload(config_module)
            for key, url in resolved.items():
                if config_module.PRODUCTS[key]["release_notes_url"] != url:
                    raise RuntimeError(f"config write verification failed for {key}")
            self.cb.on_log("info", "config.py updated and verified.")
        self.cb.on_finished("discover", resolved)
        return resolved

    def rebuild_indexes(self) -> None:
        self.cb.on_started("rebuild_indexes")
        self.cb.on_log("info", "Rebuilding indexes...")
        index_generator.generate_all(LIBRARY_BASE, PRODUCTS)
        self.cb.on_log("info", f"Indexes written to {LIBRARY_BASE}")
        self.cb.on_finished("rebuild_indexes", {})

    def scrape_product(self, product_key: str, force: bool = False) -> dict:
        return self._scrape_one(product_key, force, with_index_rebuild=True, action_label=f"scrape_{product_key}")

    def scrape_all(self, force: bool = False) -> dict:
        self.cb.on_started("scrape_all")
        report: dict = {}
        for key in PRODUCTS:
            if self.cancel.is_cancelled():
                self.cb.on_log("warning", "Cancelled — stopping scrape_all loop")
                break
            stats = self._scrape_one(key, force, with_index_rebuild=False, action_label=None)
            report[key] = stats
        try:
            self.rebuild_indexes()
        except Exception as exc:
            self.cb.on_log("error", f"Index rebuild failed: {exc}")
        self._write_report(report)
        self.cb.on_finished("scrape_all", report)
        return report

    def _scrape_one(self, product_key: str, force: bool, with_index_rebuild: bool,
                    action_label: str | None) -> dict:
        if action_label:
            self.cb.on_started(action_label)
        cfg = PRODUCTS[product_key]
        tracker = StateTracker(STATE_FILE)
        self.cb.on_log("info", f"=== {cfg['display_name']} ===")

        try:
            versions = discover_versions(cfg["space_key"])
        except Exception as exc:
            self.cb.on_log("error", f"{product_key}: discovery failed: {exc}")
            stats = {"discovered": 0, "new": 0, "skipped": 0, "failed": 0, "failed_urls": []}
            self.cb.on_status(product_key, stats)
            if action_label:
                self.cb.on_finished(action_label, stats)
            return stats

        self.cb.on_log("info", f"{product_key}: discovered {len(versions)} version page(s)")
        stats = {"discovered": len(versions), "new": 0, "skipped": 0, "failed": 0, "failed_urls": []}
        self.cb.on_status(product_key, stats)

        total = len(versions)
        with Browser() as browser:
            for idx, v in enumerate(versions, start=1):
                if self.cancel.is_cancelled():
                    self.cb.on_log("warning", f"{product_key}: cancelled before {v['version']}")
                    break

                ver, url, title = v["version"], v["url"], v["title"]
                self.cb.on_progress(product_key, ver, idx, total)

                if not force and tracker.is_scraped(product_key, ver):
                    stats["skipped"] += 1
                    self.cb.on_status(product_key, stats)
                    continue
                try:
                    browser.navigate(url)
                    browser.expand_confluence_macros()
                    shot = str(LIBRARY_BASE / product_key / "versions" / "screenshots"
                               / f"{json_writer.safe_name(ver)}.png")
                    browser.screenshot(shot)
                    data = parse_page(browser.get_content(), product_key, ver, title, url, shot,
                                      cfg["section_aliases"], COLUMN_SYNONYMS)
                    json_writer.save_version(data, LIBRARY_BASE)
                    md_writer.save_version(data, LIBRARY_BASE)
                    tracker.mark_scraped(product_key, ver, url)
                    stats["new"] += 1
                    summary = ", ".join(f"{k}={len(data[k])}" for k in
                                        ("enhancements", "bugs", "tasks", "schema_changes") if k in data) or "no sections"
                    self.cb.on_log("info", f"[OK] {ver} ({summary})")
                except Exception as exc:
                    stats["failed"] += 1
                    stats["failed_urls"].append(url)
                    self.cb.on_log("error", f"[FAIL] {ver}: {exc}")
                self.cb.on_status(product_key, stats)

        self.cb.on_log("info", f"{product_key} done: new={stats['new']} skipped={stats['skipped']} failed={stats['failed']}")
        if with_index_rebuild:
            try:
                self.rebuild_indexes()
            except Exception as exc:
                self.cb.on_log("error", f"Index rebuild failed: {exc}")
            self._write_report({product_key: stats})
        if action_label:
            self.cb.on_finished(action_label, stats)
        return stats

    def _write_report(self, report: dict) -> None:
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self.cb.on_log("info", f"Run report written to {REPORT_FILE}")
```

### `scraper/run.py`

```python
"""
Contoso KB Scraper V2.1 — CLI entry. Uses scraper.engine under the hood.
The GUI app (ContosoKBScraper.exe / scraper/gui.py) uses the same engine.
"""
from __future__ import annotations
import sys
import argparse
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.config import PRODUCTS, LOG_FILE
from scraper.engine import Engine, LoggingCallbacks, CancellationToken


def _setup_logging():
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(LOG_FILE, encoding="utf-8")],
    )


def main():
    parser = argparse.ArgumentParser(description="Contoso KB Release Notes Scraper V2.1 (CLI)")
    parser.add_argument("--product", choices=list(PRODUCTS.keys()))
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--index-only", action="store_true")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--discover", action="store_true")
    args = parser.parse_args()

    _setup_logging()
    engine = Engine(callbacks=LoggingCallbacks(), cancel_token=CancellationToken())

    if args.validate:
        sys.exit(0 if engine.validate() else 1)
    if args.discover:
        engine.discover_and_update_config(); return
    if args.index_only:
        engine.rebuild_indexes(); return
    if args.all:
        engine.scrape_all(force=args.force); return
    if args.product:
        engine.scrape_product(args.product, force=args.force); return
    parser.print_help()


if __name__ == "__main__":
    main()
```

---

## APPENDIX B — Task B file

### `scraper/gui.py`

```python
"""V2.1 desktop GUI. Run from source: scraper\\venv\\Scripts\\python.exe scraper\\gui.py
Packaged as ContosoKBScraper.exe via PyInstaller."""
from __future__ import annotations
import sys
import logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtGui import QTextCursor, QAction, QFont, QColor, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QPlainTextEdit, QProgressBar, QFrame,
    QToolBar, QStatusBar, QMessageBox,
)

from scraper.config import PRODUCTS, LOG_FILE
from scraper.engine import Engine, EngineCallbacks, CancellationToken

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8")],
)


class SignalBridge(QObject):
    log_sig      = Signal(str, str)
    status_sig   = Signal(str, dict)
    progress_sig = Signal(str, str, int, int)
    started_sig  = Signal(str)
    finished_sig = Signal(str, dict)


class BridgeCallbacks(EngineCallbacks):
    def __init__(self, bridge: SignalBridge):
        self.bridge = bridge
    def on_log(self, level, msg):                self.bridge.log_sig.emit(level, msg)
    def on_status(self, product, stats):         self.bridge.status_sig.emit(product, dict(stats))
    def on_progress(self, product, ver, i, n):   self.bridge.progress_sig.emit(product, ver, i, n)
    def on_started(self, action):                self.bridge.started_sig.emit(action)
    def on_finished(self, action, report):       self.bridge.finished_sig.emit(action, dict(report))


class Worker(QThread):
    def __init__(self, engine: Engine, action: str, kwargs: dict):
        super().__init__()
        self.engine = engine
        self.action = action
        self.kwargs = kwargs
    def run(self):
        try:
            method = getattr(self.engine, self.action)
            method(**self.kwargs)
        except Exception as exc:
            logging.exception("Worker action %s raised", self.action)
            self.engine.cb.on_log("error", f"Action {self.action} crashed: {exc}")


class StatusCard(QFrame):
    def __init__(self, product_key: str, display_name: str, on_scrape):
        super().__init__()
        self.product_key = product_key
        self.setFrameShape(QFrame.StyledPanel)
        self.setMinimumWidth(220)
        v = QVBoxLayout(self)
        title = QLabel(f"<b>{display_name}</b>")
        title.setStyleSheet("font-size: 14px;")
        v.addWidget(title)
        self.lbl_discovered = QLabel("Discovered: —")
        self.lbl_new        = QLabel("New: 0")
        self.lbl_skipped    = QLabel("Skipped: 0")
        self.lbl_failed     = QLabel("Failed: 0")
        for w in (self.lbl_discovered, self.lbl_new, self.lbl_skipped, self.lbl_failed):
            v.addWidget(w)
        row = QHBoxLayout()
        self.btn_scrape = QPushButton("Scrape")
        self.chk_force  = QCheckBox("Force")
        self.btn_scrape.clicked.connect(lambda: on_scrape(self.product_key, self.chk_force.isChecked()))
        row.addWidget(self.btn_scrape); row.addWidget(self.chk_force); row.addStretch()
        v.addLayout(row)
        v.addStretch()

    def update_stats(self, stats: dict):
        self.lbl_discovered.setText(f"Discovered: {stats.get('discovered', '—')}")
        self.lbl_new.setText(f"New: {stats.get('new', 0)}")
        self.lbl_skipped.setText(f"Skipped: {stats.get('skipped', 0)}")
        self.lbl_failed.setText(f"Failed: {stats.get('failed', 0)}")

    def set_enabled(self, enabled: bool):
        self.btn_scrape.setEnabled(enabled)
        self.chk_force.setEnabled(enabled)


class MainWindow(QMainWindow):
    MAX_LOG_LINES = 5000

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Contoso KB Scraper")
        self.resize(1100, 740)

        self.bridge = SignalBridge()
        self.cancel_token = CancellationToken()
        self.engine = Engine(callbacks=BridgeCallbacks(self.bridge), cancel_token=self.cancel_token)
        self.worker: Worker | None = None

        self._build_ui()
        self._wire_signals()
        self._set_running(False)
        self._log("info", "Ready. Use the toolbar to validate, discover, or scrape.")

    def _build_ui(self):
        central = QWidget(); self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        tb = QToolBar(); tb.setMovable(False); self.addToolBar(tb)
        self.act_validate = QAction("Validate", self); tb.addAction(self.act_validate)
        self.act_discover = QAction("Discover / Refresh URLs", self); tb.addAction(self.act_discover)
        self.act_indexes  = QAction("Rebuild Indexes", self); tb.addAction(self.act_indexes)
        tb.addSeparator()
        self.act_stop = QAction("⏹ STOP", self); tb.addAction(self.act_stop)

        cards_row = QHBoxLayout()
        self.cards: dict[str, StatusCard] = {}
        for key, cfg in PRODUCTS.items():
            card = StatusCard(key, cfg["display_name"], on_scrape=self._scrape_one)
            self.cards[key] = card
            cards_row.addWidget(card)
        outer.addLayout(cards_row)

        self.lbl_progress = QLabel("Idle")
        self.progress = QProgressBar(); self.progress.setRange(0, 100); self.progress.setValue(0)
        outer.addWidget(self.lbl_progress)
        outer.addWidget(self.progress)

        bulk = QHBoxLayout()
        self.btn_scrape_all = QPushButton("Scrape ALL (incremental)")
        self.btn_force_all  = QPushButton("Force re-scrape ALL")
        bulk.addWidget(self.btn_scrape_all); bulk.addWidget(self.btn_force_all); bulk.addStretch()
        outer.addLayout(bulk)

        outer.addWidget(QLabel("<b>Log</b>"))
        self.log_pane = QPlainTextEdit(); self.log_pane.setReadOnly(True)
        self.log_pane.setMaximumBlockCount(self.MAX_LOG_LINES)
        self.log_pane.setFont(QFont("Consolas", 9))
        outer.addWidget(self.log_pane, stretch=1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(f"Log file: {LOG_FILE}")

    def _wire_signals(self):
        self.bridge.log_sig.connect(self._log)
        self.bridge.status_sig.connect(self._on_status)
        self.bridge.progress_sig.connect(self._on_progress)

        self.act_validate.triggered.connect(lambda: self._start("validate"))
        self.act_discover.triggered.connect(lambda: self._start("discover_and_update_config"))
        self.act_indexes.triggered.connect(lambda: self._start("rebuild_indexes"))
        self.act_stop.triggered.connect(self._stop)
        self.btn_scrape_all.clicked.connect(lambda: self._start("scrape_all", {"force": False}))
        self.btn_force_all.clicked.connect(lambda: self._start("scrape_all", {"force": True}))

    def _start(self, action: str, kwargs: dict | None = None):
        if self.worker and self.worker.isRunning():
            self._log("warning", "A run is already in progress; ignoring request.")
            return
        self.cancel_token = CancellationToken()
        self.engine.cancel = self.cancel_token
        self.worker = Worker(self.engine, action, kwargs or {})
        self.worker.finished.connect(self._worker_done)
        self._set_running(True)
        self._log("info", f"--- Starting: {action} ---")
        self.worker.start()

    def _scrape_one(self, product_key: str, force: bool):
        self._start("scrape_product", {"product_key": product_key, "force": force})

    def _stop(self):
        if self.worker and self.worker.isRunning():
            self._log("warning", "Cancel requested — will stop after current page completes.")
            self.cancel_token.cancel()

    def _worker_done(self):
        self._set_running(False)
        self._log("info", "--- Run complete ---")
        self.lbl_progress.setText("Idle")
        self.progress.setValue(0)

    def _set_running(self, running: bool):
        for act in (self.act_validate, self.act_discover, self.act_indexes):
            act.setEnabled(not running)
        for btn in (self.btn_scrape_all, self.btn_force_all):
            btn.setEnabled(not running)
        for card in self.cards.values():
            card.set_enabled(not running)
        self.act_stop.setEnabled(running)

    @Slot(str, str)
    def _log(self, level: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"{ts} {level.upper():7s} {msg}"
        cursor = self.log_pane.textCursor()
        fmt = QTextCharFormat()
        if level == "error":     fmt.setForeground(QColor("#c62828"))
        elif level == "warning": fmt.setForeground(QColor("#ef6c00"))
        elif level == "info":    fmt.setForeground(QColor("#212121"))
        else:                    fmt.setForeground(QColor("#616161"))
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(line + "\n", fmt)
        self.log_pane.setTextCursor(cursor)
        self.log_pane.ensureCursorVisible()
        getattr(logging, level if level in ("debug","info","warning","error","critical") else "info")(msg)

    @Slot(str, dict)
    def _on_status(self, product: str, stats: dict):
        card = self.cards.get(product)
        if card:
            card.update_stats(stats)

    @Slot(str, str, int, int)
    def _on_progress(self, product: str, version: str, idx: int, total: int):
        self.lbl_progress.setText(f"Now scraping: {product} — {version}   ({idx} / {total})")
        pct = int(idx * 100 / total) if total else 0
        self.progress.setValue(pct)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(self, "Quit?",
                "A scrape is running. Stop it and quit?",
                QMessageBox.Yes | QMessageBox.No)
            if reply != QMessageBox.Yes:
                event.ignore(); return
            self.cancel_token.cancel()
            self.worker.wait(15_000)
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Contoso KB Scraper")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

---

## APPENDIX C — Task C files

### `ContosoKBScraper.spec`

```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("playwright", "PySide6"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
hiddenimports += ["bs4", "lxml", "lxml._elementpath"]

a = Analysis(
    ["scraper/gui.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="ContosoKBScraper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
```

### `build_exe.bat`

```batch
@echo off
setlocal
pushd "%~dp0"
echo Building ContosoKBScraper.exe...
"scraper\venv\Scripts\python.exe" -m PyInstaller ContosoKBScraper.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo.
echo Build complete. Artifact: dist\ContosoKBScraper.exe
pause
popd
endlocal
```
