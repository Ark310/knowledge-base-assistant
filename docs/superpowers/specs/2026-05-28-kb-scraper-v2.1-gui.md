# Design: Contoso KB Scraper V2.1 — Desktop App
**Date:** 2026-05-28
**Supersedes UI layer of:** `2026-05-27-kb-scraper-v2-design.md` (the scraper engine stays the same; only the launcher/UI changes)

---

## Why V2.1

V2's `Launch.bat` is unfit for the job:
1. It closed silently when option 4 was pressed — root cause: cmd's well-known quirk where `goto LABEL` inside a parenthesized `if (...)` block exits the script.
2. Even when it works, a `.bat` menu gives **no visibility, no live monitoring, and no way to stop a long run** — exactly what is needed during a 156-page scrape.
3. "Did anything happen?" / "Where is it now?" / "I want to stop" — none answerable from the .bat.

V2.1 replaces the launcher with a **PySide6 desktop application** packaged as a single Windows `.exe`. The scraper engine (discovery, parser, writers, state, config) is unchanged.

---

## Goal

A double-clickable `ContosoKBScraper.exe` that stays open as long as the user wants, shows what the scraper is doing in real time, and lets the user stop it cleanly at any moment.

---

## Architecture

```
Knowledge Base/
├── scraper/
│   ├── engine.py        ← NEW: orchestration class with callbacks + cancel token
│   ├── gui.py           ← NEW: PySide6 main window + QThread worker
│   ├── run.py           ← thin CLI wrapper around engine.py (existing modes unchanged)
│   ├── config.py        ← freeze-aware BASE_DIR (resolves to exe-folder when frozen)
│   ├── discovery.py     ← unchanged
│   ├── core.py          ← unchanged
│   ├── parsers/         ← unchanged
│   ├── writers/         ← unchanged
│   ├── config_writer.py ← unchanged
│   └── ContosoKBScraper.spec   ← PyInstaller spec
├── build_exe.bat        ← one-line PyInstaller invocation for builds
└── dist/ContosoKBScraper.exe   ← built artifact
```

### engine.py — orchestration as a class

```python
class CancellationToken:
    def __init__(self) -> None: self._cancelled = False
    def cancel(self) -> None: self._cancelled = True
    def is_cancelled(self) -> bool: return self._cancelled

class EngineCallbacks:
    """No-op base; GUI subclasses to push to Qt signals, CLI uses default logging."""
    def on_log(self, level: str, msg: str) -> None: ...
    def on_status(self, product: str, stats: dict) -> None: ...
    def on_progress(self, product: str, version: str, idx: int, total: int) -> None: ...
    def on_started(self, action: str) -> None: ...
    def on_finished(self, action: str, report: dict) -> None: ...

class Engine:
    def __init__(self, callbacks: EngineCallbacks, cancel_token: CancellationToken): ...
    def validate(self) -> bool: ...
    def discover_and_update_config(self) -> dict: ...
    def rebuild_indexes(self) -> None: ...
    def scrape_product(self, product: str, force: bool) -> dict: ...   # returns stats
    def scrape_all(self, force: bool) -> dict: ...                     # returns full report
```

- Between versions, `scrape_product` checks `cancel_token.is_cancelled()` and stops gracefully (emits a "cancelled" log + completes current report). State (`scraped_versions.json`) is committed after each version, so a cancel never leaves half-written records.
- `run.py` constructs default callbacks that just route to Python's `logging` (CLI behaviour unchanged) and never wires the cancel token, so CLI users see exactly what V2 produced.

### gui.py — PySide6 desktop window

Single `QMainWindow` with three regions:

```
┌────────────────────────────────────────────────────────────────┐
│  [Validate] [Discover] [Rebuild Indexes]            [ ⏹ STOP ] │   ← top toolbar
├────────────────────────────────────────────────────────────────┤
│  ┌─TradeDesk──────┐ ┌─Web4─────────┐ ┌─SalesHub──────┐           │   ← status cards
│  │ Discovered 117│ │ Discovered 18│ │ Discovered 21│           │
│  │ New 12 Skip 105│ │ New 0 Skip 18│ │ New 21 Skip 0│           │
│  │ Failed 0      │ │ Failed 0     │ │ Failed 0     │           │
│  │ [Scrape] [Force]│ ...                                       │
│  └───────────────┘ ...                                         │
├────────────────────────────────────────────────────────────────┤
│  Now scraping: SalesHub — 2.0.2.1   (12 / 21)  [████░░░░░░] 55% │   ← progress bar
├────────────────────────────────────────────────────────────────┤
│  09:32:14 INFO === SalesHub ===                                 │
│  09:32:15 INFO saleshub: discovered 21 version page(s)          │
│  09:32:17 INFO [OK] 2.0.0.0 (enhancements=4, schema_changes=2) │   ← log stream
│  09:32:19 INFO [OK] 2.0.0.1 (...)                              │
│  ...                                                            │
└────────────────────────────────────────────────────────────────┘
                                              [Scrape All] [Force All]
```

- **Worker thread:** A `QThread` subclass holds an `Engine` and runs whichever method the user invokes. Engine callbacks emit Qt signals via a small `QObject` proxy so the GUI thread can safely update widgets.
- **Stop button:** sets `cancel_token.cancel()`. Disabled when no run is active.
- **Log pane:** `QPlainTextEdit` (read-only, auto-scrolling, capped at 5000 lines to bound memory). Coloured by level.
- **Status cards:** three custom widgets, one per product, updated via `on_status`.
- **Progress bar:** updated via `on_progress`. Hidden when idle.
- **Idle vs running:** action buttons grey out while a worker is active (except Stop). When done, app stays open; the user can run again or close.
- **Errors anywhere in the engine** are caught, logged to the UI, and the app continues. The GUI never crashes.

### config.py — freeze-aware paths

When the app runs from a PyInstaller frozen exe, `__file__` points into a temp directory PyInstaller extracts to. Library/state must live next to the **exe**, not the temp dir. Pattern:

```python
import sys
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.parent
```

`LIBRARY_BASE`, `STATE_DIR`, etc. derive from `BASE_DIR` as before. CLI behaviour is unchanged.

### PyInstaller packaging

- `ContosoKBScraper.spec` — bundles `scraper/gui.py` as entry, hidden imports for `playwright._impl`, `bs4`, `lxml`, and `--collect-all playwright` so the driver is shipped.
- `--onefile --windowed --name ContosoKBScraper` (no console window; output goes to the GUI log pane and the disk log file).
- Uses your installed **system Chrome** via `channel="chrome"` (no Chromium bundle in the exe — keeps size ~100 MB, not ~300 MB).
- `build_exe.bat` runs `pyinstaller ContosoKBScraper.spec --clean --noconfirm`.

### Cancel semantics

Cooperative cancel. The `Engine.scrape_product` loop is shaped:

```python
for v in versions:
    if self.cancel.is_cancelled():
        self.cb.on_log("warning", f"{product}: cancelled before {v['version']}")
        break
    # ... scrape one page ...
```

So pressing Stop finishes the version currently in flight (a few seconds), commits its state, and exits the loop cleanly. No corrupted JSON, no half-written screenshot.

---

## Testing

- `test_engine.py` — new: validates that the engine emits the expected callback sequence for `validate()`, that `scrape_product` honours `cancel_token` (using a fake browser and discovery, so no network), and that `on_status`/`on_progress` are called per page.
- All existing 46 V2 tests stay green (engine refactor is API-additive; the underlying modules are unchanged).

GUI is not unit-tested (industry-standard for Qt apps); it is exercised by the smoke test (Task D).

---

## Non-Goals

- No installer (MSI/Inno) — single-file exe is enough.
- No system Chromium bundle — uses installed Chrome via `channel="chrome"`.
- No dark-theme toggle, no settings persistence, no auto-update — keep the surface area tight.
- No CLI removal — `python scraper/run.py --all` still works for power users; the engine is shared.
