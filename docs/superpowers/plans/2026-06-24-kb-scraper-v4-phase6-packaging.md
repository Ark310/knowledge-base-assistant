# KB Scraper v4 — Phase 6: Packaging & Ship — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Produce the shippable v4 build: a **one-folder** PyInstaller exe that opens in well under a minute, carries the **ice-scraper icon**, launches from a single themed entry point (`app.py`), and uses the system Chrome (no bundled browser). Gated by a full test pass and an **operator-confirmed smoke run** before any build (standing rule).

**Architecture:** `gui.py`'s leftover `main()` is collapsed into `app.py` (one themed entry). `config.py`'s frozen-path logic is corrected for the one-folder layout (exe lives in `dist-v4/ContosoKBScraper-v4/`). A new one-folder `.spec` (`COLLECT`, `exclude_binaries`) bundles PySide6 + the Playwright driver + `assets/`, with the icon. The build runs into a fresh `--workpath`/`--distpath` to dodge the OneDrive lock.

**Tech Stack:** PyInstaller, PySide6, Playwright (system Chrome via `channel="chrome"`), pytest. Test interpreter `scraper\venv\Scripts\python.exe`. Builds on Phase 5 (branch `feat/kb-scraper-v4`, head `fd65e3c`).

## Global Constraints
- **No exe is built until the operator confirms a fresh smoke run** (standing rule — Task 3 blocks on it). The smoke already passed live on 76511 + 76091.
- `APP_VERSION` is already `"4.0"` (Phase 3); add a test pinning it.
- One-folder build (`COLLECT`) — NOT one-file — for fast startup (no per-launch temp extraction).
- We use the user's installed Chrome (`channel="chrome"`); do not ship a browser. Keep the Playwright python package + its node driver (needed for the sync API).
- Password/keyring untouched; verify nothing writes a password/token to disk or logs.
- Build into fresh `--workpath build_v4 --distpath dist-v4` (the OneDrive `--clean` lock issue — see cerebrum).

---

### Task 1: Single themed entry point + version test + frozen path

**Files:** Modify `scraper/gui.py` (collapse `main()`), `scraper/config.py` (frozen BASE_DIR for one-folder); Create `tests/test_version.py`.

- [ ] **Step 1: Failing test.**
```python
# tests/test_version.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.config import APP_VERSION

def test_app_version_is_4_0():
    assert APP_VERSION == "4.0"
```
- [ ] **Step 2: Run — expect PASS already** (version is 4.0). (This test guards future bumps; it's the "version surfacing" gate.) If it somehow fails, fix `config.APP_VERSION`.
- [ ] **Step 3: Single entry point.** In `scraper/gui.py`, replace the body of `main()` with a delegation so there is ONE themed entry:
```python
def main():
    # Single themed entry point — delegate to app.main() (stylesheet + splash + icon).
    from scraper.app import main as app_main
    app_main()
```
  (Leave `if __name__ == "__main__": main()` so `python scraper/gui.py` still works and is themed.)
- [ ] **Step 4: Frozen path for one-folder.** In `scraper/config.py`, the frozen branch currently assumes one-FILE (`BASE_DIR = Path(sys.executable).parent.parent`). For the one-folder build the exe lives in `dist-v4/ContosoKBScraper-v4/`, so the project root is one level deeper. Update:
```python
if getattr(sys, "frozen", False):
    _EXE_DIR  = Path(sys.executable).parent            # dist-v4/ContosoKBScraper-v4/
    # one-folder layout: exe-dir -> dist-v4 -> project root
    BASE_DIR  = _EXE_DIR.parent.parent
    STATE_DIR = _EXE_DIR / "state"                      # writable, next to the exe
else:
    BASE_DIR  = Path(__file__).parent.parent
    STATE_DIR = Path(__file__).parent / "state"
LIBRARY_BASE = BASE_DIR / "library"
```
  (Output folders are user-overridable in Settings; this default writes to the existing `library/` when the exe runs in-place under the project. Add a one-line comment saying so.)
- [ ] **Step 5: Run full suite** (`scraper\venv\Scripts\python.exe -m pytest tests/ -q`) — green; offscreen build smoke (`from scraper.gui import main`) imports cleanly.
- [ ] **Step 6: Commit.** `git add scraper/gui.py scraper/config.py tests/test_version.py && git commit -m "feat(v4): single themed entry (gui.main->app.main) + one-folder frozen path + version test"`

---

### Task 2: One-folder PyInstaller spec + build batch

**Files:** Create `ContosoKBScraper-v4.spec`; Create `build_scraper_exe.bat`. Read first: the existing `ContosoKBScraper.spec` (old one-file) + `ContosoKBChatbot.spec` (the one-folder COLLECT pattern).

- [ ] **Step 1: Write `ContosoKBScraper-v4.spec`.**
```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("playwright", "PySide6"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

datas += [("assets", "assets")]   # logos + ice-scraper icon (theme.asset_path reads sys._MEIPASS/assets when frozen)
hiddenimports += [
    "bs4", "lxml", "lxml._elementpath",
    "keyring", "keyring.backends", "keyring.backends.Windows",
    "keyring.backends.fail", "keyring.credentials",
]

a = Analysis(
    ["scraper/app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[], runtime_hooks=[],
    excludes=[
        # QtWidgets-only app — drop the heavy Qt modules we never import
        # (QtWebEngine alone is ~150 MB; we scrape via Playwright's browser).
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DExtras", "PySide6.Qt3DAnimation",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,           # one-folder: binaries go in COLLECT, not the exe
    name="ContosoKBScraper",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False,
    icon="assets/scraper_icon.ico",
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="ContosoKBScraper-v4",
)
```
- [ ] **Step 2: Write `build_scraper_exe.bat`.**
```bat
@echo off
REM One-folder v4 build into fresh work/dist paths (OneDrive --clean lock workaround).
scraper\venv\Scripts\python.exe -m PyInstaller ContosoKBScraper-v4.spec --noconfirm --workpath build_v4 --distpath dist-v4
echo Build complete: dist-v4\ContosoKBScraper-v4\ContosoKBScraper.exe
```
- [ ] **Step 3: Commit** (spec + batch only — do NOT build yet). `git add ContosoKBScraper-v4.spec build_scraper_exe.bat && git commit -m "build(v4): one-folder PyInstaller spec + build batch (app.py entry, ice-scraper icon)"`

---

### Task 3: Smoke gate → build → frozen-boot verify (CONTROLLER + OPERATOR)

This task is run by the controller; the build + the live verification need the operator.

- [ ] **Step 1: Full suite green.** `scraper\venv\Scripts\python.exe -m pytest tests/ -q`.
- [ ] **Step 2: Operator smoke gate.** Confirm with the user that the live smoke is good (already passed on 76511 + 76091) and they approve building. Do NOT proceed without explicit approval.
- [ ] **Step 3: Build.** Run `build_scraper_exe.bat` (PyInstaller, one-folder, ~minutes; runs in background). Watch for errors (missing hiddenimports, OneDrive lock).
- [ ] **Step 4: Frozen-boot verify.** Confirm `dist-v4/ContosoKBScraper-v4/ContosoKBScraper.exe` exists; launch it and confirm: the splash + window appear in <1 min, the **ice-scraper icon** shows on the window/taskbar, both tabs render, and a real ticket/KB scrape works (system Chrome launches via `channel="chrome"`). The operator runs the full scrape check; the controller confirms the exe starts without a frozen-boot crash.
- [ ] **Step 5: Security check.** Confirm no password/token is written under `dist-v4/.../state` or any log during a run (grep the run.log + state files).
- [ ] **Step 6: Commit** any build-fix tweaks (spec hiddenimports etc.) discovered during the build.

---

### Task 4: Finish the v4 branch

- [ ] **Step 1:** Final review of the Phase 6 diff (base = Phase-5 head `fd65e3c`); fix Critical/Important.
- [ ] **Step 2:** Update `.superpowers/sdd/progress.md` + memory: v4 COMPLETE (all 6 phases), built + verified.
- [ ] **Step 3:** Invoke **superpowers:finishing-a-development-branch** — present the user with the options for the whole `feat/kb-scraper-v4` branch (merge to master/main, open a PR, or keep unmerged — their call, consistent with the chatbot pattern). Do not merge without explicit instruction.

---

## Self-Review
- **Spec coverage:** lighter/faster one-folder exe (Task 2), ice-scraper icon baked in (Task 2 + Phase 3 asset), single themed entry (Task 1), version 4.0 pinned (Task 1), smoke-gated build (Task 3), ship (Task 4). From the v4 spec §9 + §11. ✅
- **Placeholders:** Task 1/2 carry full code (entry, config path, .spec, batch); Task 3 is an inherently interactive build/verify procedure with exact commands + the operator gate; Task 4 hands off to finishing-a-development-branch. ✅
- **Type consistency:** entry `app.main()` (Phase 3) ↔ `gui.main()` delegation; `theme.asset_path` reads `sys._MEIPASS/assets` ↔ `.spec` `datas [("assets","assets")]`; `APP_VERSION=="4.0"` ↔ Phase-3 bump. ✅
- **Risk:** one-folder frozen path assumes the exe ships under the project's `dist-v4/` (Settings overrides output anyway); the build may surface a missing hiddenimport (fix + recommit in Task 3). Build is environment-specific — verified by launching, not unit tests.
