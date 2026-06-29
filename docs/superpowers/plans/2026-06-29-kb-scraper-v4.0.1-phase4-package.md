# KB Scraper v4.0.1 — Phase 4: Parity Pass + Version + Package — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Tasks 3-5 are interactive (controller + operator). Steps use checkbox (`- [ ]`).

**Goal:** Ship v4.0.1: a broader legacy parity pass, version → **4.0.1**, and a one-folder exe packaged into the **main `dist/`** folder (`dist/ContosoKBScraper-v4.0.1/`), then finish the branch.

**Architecture:** Same one-folder PyInstaller approach as v4.0 (entry `scraper/app.py`, system Chrome via `channel="chrome"`, heavy-Qt excludes), retargeted to `--distpath dist`. The frozen `BASE_DIR = _EXE_DIR.parent.parent` is already correct for `dist/<name>/` (exe two levels under repo root, same as `dist-v4/<name>/`). Both portal tabs ship in the one exe.

**Tech Stack:** PyInstaller, PySide6, async Playwright, pytest. Test interpreter `scraper\venv\Scripts\python.exe`. Builds on Phase 3 (branch `feat/kb-scraper-v4.0.1`, head `06fc92c`).

## Global Constraints
- **No exe build until the operator confirms a fresh smoke/live run** (standing rule — Task 4 blocks on it).
- Password → OS keyring only; no PII/secrets in logs. System Chrome (`channel="chrome"`), no bundled browser.
- Build into fresh `--workpath build_v401 --distpath dist` (OneDrive `--clean` lock workaround).
- Light mode default; both tabs (tradedesk + Legacy) + KB ship together.

---

### Task 1: Version → 4.0.1

**Files:** Modify `scraper/config.py` (APP_VERSION + changelog), `tests/test_version.py`.

- [ ] **Step 1:** In `scraper/config.py` set `APP_VERSION = "4.0.1"` and prepend a changelog line:
```
v4.0.1  2026-06-29  Async rewrite (light single-window default + multi-window toggle,
        fixes the high-worker freeze); resolution-file/thread completeness; Legacy
        contoso.example portal tab at parity (internal comments + view_attachment files).
```
- [ ] **Step 2:** Update `tests/test_version.py`: rename the test + assert `APP_VERSION == "4.0.1"`:
```python
def test_app_version_is_4_0_1():
    assert APP_VERSION == "4.0.1"
```
- [ ] **Step 3:** Run `scraper\venv\Scripts\python.exe -m pytest tests/test_version.py -v` → pass. Full suite green.
- [ ] **Step 4:** Commit `git add scraper/config.py tests/test_version.py && git commit -m "chore(v4.0.1): version 4.0.1 + changelog"`

---

### Task 2: One-folder spec + build batch (into dist/)

**Files:** Create `ContosoKBScraper-v4.0.1.spec`, `build_scraper_exe_v401.bat`.

- [ ] **Step 1:** Create `ContosoKBScraper-v4.0.1.spec` — identical to `ContosoKBScraper-v4.spec` EXCEPT the COLLECT name. Concretely:
```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("playwright", "PySide6"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

datas += [("assets", "assets")]
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
    exclude_binaries=True,
    name="ContosoKBScraper",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False,
    icon="assets/scraper_icon.ico",
)
coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="ContosoKBScraper-v4.0.1",
)
```
- [ ] **Step 2:** Create `build_scraper_exe_v401.bat`:
```bat
@echo off
REM One-folder v4.0.1 build into the MAIN dist/ folder (fresh workpath; OneDrive lock workaround).
scraper\venv\Scripts\python.exe -m PyInstaller ContosoKBScraper-v4.0.1.spec --noconfirm --workpath build_v401 --distpath dist
echo Build complete: dist\ContosoKBScraper-v4.0.1\ContosoKBScraper.exe
```
- [ ] **Step 3:** Spec parses: `scraper\venv\Scripts\python.exe -c "compile(open('ContosoKBScraper-v4.0.1.spec',encoding='utf-8').read(),'spec','exec'); print('spec-ok')"`.
- [ ] **Step 4:** Commit `git add -f ContosoKBScraper-v4.0.1.spec build_scraper_exe_v401.bat && git commit -m "build(v4.0.1): one-folder spec + batch -> dist/ContosoKBScraper-v4.0.1/"`

---

### Task 3: Broader legacy parity pass + smoke gate (controller + operator)

- [ ] **Step 1:** Full suite green.
- [ ] **Step 2:** Controller drives a legacy batch via keyring creds (reuse scratchpad `live_contoso_smoke.py` / `live_async_batch.py` with the contoso wiring): scrape **71456–71467** on contoso (light, workers=4). Confirm no stranded tickets, comments/attachments/images captured (counts only, no PII). Spot-compare a couple against tradedesk for category parity. Log results to the ledger.
- [ ] **Step 3:** Operator smoke gate — confirm the live runs (tradedesk golden + legacy golden + the legacy batch) are good and they approve building. Do NOT build without explicit approval.

---

### Task 4: Build + frozen-boot verify (controller + operator)

- [ ] **Step 1:** Run `build_scraper_exe_v401.bat` (background; ~minutes; watch for missing hiddenimports / OneDrive lock).
- [ ] **Step 2:** Confirm `dist/ContosoKBScraper-v4.0.1/ContosoKBScraper.exe` exists; `_internal/assets/scraper_icon.ico` + `_internal/playwright/driver/` bundled; icon embedded.
- [ ] **Step 3:** Frozen-boot: launch the exe; confirm it boots < 1 min, ice-scraper icon, **3 tabs** (Tickets — tradedesk / Tickets — Legacy / Knowledge Base). Operator runs a real ticket on each portal from the exe (light mode); confirms system Chrome launches and output lands in the configured folders.
- [ ] **Step 4:** Security check: grep `dist/ContosoKBScraper-v4.0.1/state` + run.log for credential leaks (counts only) — expect 0; settings hold only url/username/paths/browser_mode (password keyring-only).
- [ ] **Step 5:** Commit any build-fix tweaks.

---

### Task 5: Finish the v4.0.1 branch

- [ ] **Step 1:** Final review of the Phase-4 diff (base = Phase-3 head `06fc92c`) — version/spec/batch correctness; fix Critical/Important.
- [ ] **Step 2:** Consolidate memory: replace the over-granular `project_kb_scraper_v401_p3t1.md` MEMORY.md entry with ONE `project_kb_scraper_v401.md` covering v4.0.1 (Phases 1-4). Update the SDD ledger: v4.0.1 COMPLETE.
- [ ] **Step 3:** Invoke **superpowers:finishing-a-development-branch** — present merge/PR/keep options for `feat/kb-scraper-v4.0.1` (user's call). Do not merge without explicit instruction.

---

## Self-Review
- **Spec coverage:** version 4.0.1 (T1), one-folder into main dist/ (T2), broader legacy parity (T3), smoke-gated build + frozen-boot + 3-tab verify (T3/T4), finish (T5). Matches spec Phase 4. ✅
- **Placeholders:** T1/T2 carry full code; T3/T4 are interactive build/verify procedures with exact commands + the operator gate; T5 hands off to finishing-a-development-branch. ✅
- **Type consistency:** APP_VERSION "4.0.1" ↔ test_version assertion; spec COLLECT name `ContosoKBScraper-v4.0.1` ↔ batch `--distpath dist` ↔ frozen `BASE_DIR=_EXE_DIR.parent.parent` (exe at dist/<name>/). ✅
- **Risk:** build is environment-specific (verified by launching, not unit tests); operator-gated per standing rule. dist-v4/ (v4.0) left as-is; v4.0.1 goes to dist/.
