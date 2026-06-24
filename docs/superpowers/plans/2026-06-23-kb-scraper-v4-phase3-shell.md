# KB Scraper v4 — Phase 3: Theme, App Shell & Settings — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Give the scraper the chatbot's enterprise look — branded theme, animated splash, an ice-scraper window/exe icon — and a **Settings** dialog that configures per-type output folders (Tickets / Knowledge Base) and the portal credentials (hidden until needed).

**Architecture:** A new import-light `theme.py` holds the brand palette + app stylesheet (ported from the chatbot). `app_settings.py` persists the two output paths (JSON). `settings_dialog.py` is a modal `QDialog` editing those paths + the portal credentials. `app.py` becomes the entry point: it applies the stylesheet, shows an animated branded splash, sets the window/exe icon, and opens the (theme-applied) `MainWindow` shell — which gains a branded top bar and a ⚙ Settings button. Tab *content* (Tickets/KB restyle, 2-tab restructure) stays for Phases 4–5; this phase themes the existing shell and adds Settings.

**Tech Stack:** PySide6, Pillow (icon), pytest. Test interpreter `scraper\venv\Scripts\python.exe`. Builds on Phase 2 (branch `feat/kb-scraper-v4`, head `867a393`). Qt GUI is tested **offscreen** (`QT_QPA_PLATFORM=offscreen`) — the chatbot's pattern (construct widgets, assert no crash + key widgets/objectNames present; offscreen renders text as tofu but layout/objects are valid).

## Global Constraints
- Brand theme is **ported from `Dev/kb_chatbot/gui.py`** — reuse its exact values: primary blue `#51639e`, warm secondary `#de9b6f`, light surfaces, `FONT_STACK` (Segoe UI). Do not invent a new palette.
- Password: keyring only (via existing `scraper.ticket_settings`), never on disk, never logged, masked field.
- Output paths **default to the current locations**: Tickets → `LIBRARY_BASE/"tickets"`, KB → `LIBRARY_BASE/"kb"`. Existing behavior must be unchanged until the user changes them. Persist to `STATE_DIR/"app_settings.json"`.
- Keep `theme.py` / `app.py` top-level imports light (PySide6 + config/settings only) so the splash paints immediately; import engines/Playwright lazily (they already are, in the tabs).
- Do NOT change the scraping engines, parser, or adapter in this phase. Do NOT rewrite tab *content* (Phases 4–5). `gui.py` may be edited only to host the theme/top-bar/Settings button.
- The exe entry point switch (gui.py → app.py) and the `.spec` icon happen in Phase 6; this phase just creates `app.py` + the `.ico`.

---

### Task 1: `app_settings.py` — per-type output paths

**Files:** Create `scraper/app_settings.py`; Test `tests/test_app_settings.py`

**Interfaces:**
- Produces: `load() -> dict`, `save(tickets_dir: str, kb_dir: str) -> None`, `tickets_dir() -> Path`, `kb_dir() -> Path`. Defaults: `LIBRARY_BASE/"tickets"` and `LIBRARY_BASE/"kb"`. Stored in `STATE_DIR/"app_settings.json"` as `{"tickets_dir": "...", "kb_dir": "..."}`.

- [ ] **Step 1: Failing tests.**
```python
# tests/test_app_settings.py
import sys, json, importlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

def _fresh(tmp_path, monkeypatch):
    import scraper.config as config
    monkeypatch.setattr(config, "STATE_DIR", tmp_path, raising=True)
    monkeypatch.setattr(config, "LIBRARY_BASE", tmp_path / "library", raising=True)
    import scraper.app_settings as aps
    importlib.reload(aps)
    return aps

def test_defaults_when_no_file(tmp_path, monkeypatch):
    aps = _fresh(tmp_path, monkeypatch)
    assert aps.tickets_dir() == tmp_path / "library" / "tickets"
    assert aps.kb_dir() == tmp_path / "library" / "kb"

def test_round_trip(tmp_path, monkeypatch):
    aps = _fresh(tmp_path, monkeypatch)
    aps.save(str(tmp_path / "T"), str(tmp_path / "K"))
    assert aps.tickets_dir() == tmp_path / "T"
    assert aps.kb_dir() == tmp_path / "K"
    assert json.loads((tmp_path / "app_settings.json").read_text())["tickets_dir"] == str(tmp_path / "T")

def test_partial_file_falls_back(tmp_path, monkeypatch):
    aps = _fresh(tmp_path, monkeypatch)
    (tmp_path / "app_settings.json").write_text(json.dumps({"tickets_dir": str(tmp_path / "T")}))
    assert aps.tickets_dir() == tmp_path / "T"
    assert aps.kb_dir() == tmp_path / "library" / "kb"   # missing key -> default
```
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement.**
```python
# scraper/app_settings.py
"""Persisted app settings: per-type output folders (Tickets / Knowledge Base).
Defaults preserve the current locations so behavior is unchanged until the user edits them.
"""
from __future__ import annotations
import json
from pathlib import Path

def _file() -> Path:
    from scraper.config import STATE_DIR
    return Path(STATE_DIR) / "app_settings.json"

def _default_tickets() -> Path:
    from scraper.config import LIBRARY_BASE
    return Path(LIBRARY_BASE) / "tickets"

def _default_kb() -> Path:
    from scraper.config import LIBRARY_BASE
    return Path(LIBRARY_BASE) / "kb"

def load() -> dict:
    try:
        p = _file()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def save(tickets_dir: str, kb_dir: str) -> None:
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"tickets_dir": str(tickets_dir), "kb_dir": str(kb_dir)}, indent=2),
                 encoding="utf-8")

def tickets_dir() -> Path:
    v = load().get("tickets_dir")
    return Path(v) if v else _default_tickets()

def kb_dir() -> Path:
    v = load().get("kb_dir")
    return Path(v) if v else _default_kb()
```
- [ ] **Step 4: Run — expect PASS (3).** Full suite — no regressions.
- [ ] **Step 5: Commit.** `git add scraper/app_settings.py tests/test_app_settings.py && git commit -m "feat(v4): app_settings for per-type output folders"`

---

### Task 2: `theme.py` — brand palette + app stylesheet (ported)

**Files:** Create `scraper/theme.py`; Test `tests/test_theme.py`. Read first: `Dev/kb_chatbot/gui.py` (its `PALETTE`, `FONT_STACK`, `_app_stylesheet`, `_asset_path`/`_asset_file_url`).

**Interfaces:**
- Produces: `PALETTE: dict` (keys at least: `brand`, `brand_deep`, `warm`, `bg`, `surface`, `border`, `text`, `muted`), `FONT_STACK: str`, `app_stylesheet() -> str` (QSS string using PALETTE values, incl. a `PrimaryButton` objectName rule), `asset_path(name) -> Path|None`, `asset_file_url(name) -> str|None` (freeze-aware, mirroring the chatbot).

- [ ] **Step 1: Failing tests.**
```python
# tests/test_theme.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper import theme

def test_palette_has_brand_colors():
    for k in ("brand", "warm", "bg", "surface", "text"):
        assert k in theme.PALETTE and theme.PALETTE[k].startswith("#")
    assert theme.PALETTE["brand"].lower() == "#51639e"

def test_stylesheet_references_brand_and_font():
    qss = theme.app_stylesheet()
    assert isinstance(qss, str) and len(qss) > 100
    assert theme.PALETTE["brand"] in qss
    assert "QPushButton" in qss and "PrimaryButton" in qss

def test_font_stack_is_segoe():
    assert "Segoe UI" in theme.FONT_STACK
```
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** `scraper/theme.py` by porting the chatbot's palette/stylesheet. Concrete skeleton (fill the QSS body from `Dev/kb_chatbot/gui.py._app_stylesheet`, adapting widget selectors the scraper uses — QTabWidget, QGroupBox, QTableWidget, QPlainTextEdit, QPushButton, `#PrimaryButton`):
```python
# scraper/theme.py
"""Contoso brand theme for the v4 scraper — palette + app-wide QSS, ported from the
KB Chatbot (Dev/kb_chatbot/gui.py). Import-light (PySide6 + stdlib only) so the splash
paints before any heavy import."""
from __future__ import annotations
import sys
from pathlib import Path

PALETTE = {
    "brand":      "#51639e",
    "brand_deep": "#3f4f82",
    "warm":       "#de9b6f",
    "bg":         "#eef1f7",
    "surface":    "#ffffff",
    "surface_2":  "#f6f8fc",
    "border":     "#dfe4ee",
    "text":       "#1e2536",
    "muted":      "#6b7480",
}
FONT_STACK = "'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"

def asset_path(name: str) -> Path | None:
    base = Path(sys._MEIPASS) / "assets" if getattr(sys, "frozen", False) else Path(__file__).parent.parent / "assets"
    p = base / name
    return p if p.exists() else None

def asset_file_url(name: str) -> str | None:
    p = asset_path(name)
    return p.resolve().as_uri() if p else None

def app_stylesheet() -> str:
    P = PALETTE
    return f"""
    QWidget {{ background: {P['bg']}; color: {P['text']}; font-family: {FONT_STACK}; font-size: 13px; }}
    QTabWidget::pane {{ border: 1px solid {P['border']}; background: {P['surface']}; }}
    QTabBar::tab {{ background: {P['surface_2']}; color: {P['muted']}; padding: 8px 16px; border: 0; }}
    QTabBar::tab:selected {{ color: {P['brand']}; border-bottom: 2px solid {P['brand']}; background: {P['surface']}; }}
    QGroupBox {{ background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 8px; margin-top: 8px; padding: 8px; }}
    QPlainTextEdit, QLineEdit, QTableWidget {{ background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 6px; }}
    QHeaderView::section {{ background: {P['surface_2']}; color: {P['muted']}; border: 0; padding: 6px; }}
    QPushButton {{ background: {P['surface']}; border: 1px solid {P['border']}; border-radius: 6px; padding: 6px 12px; }}
    QPushButton:hover {{ border-color: {P['brand']}; }}
    QPushButton#PrimaryButton {{ background: {P['brand']}; color: white; border: 0; font-weight: bold; }}
    QPushButton#PrimaryButton:hover {{ background: {P['brand_deep']}; }}
    QProgressBar {{ border: 0; background: #e4e8f2; border-radius: 6px; height: 10px; }}
    QProgressBar::chunk {{ background: {P['brand']}; border-radius: 6px; }}
    """
```
- [ ] **Step 4: Run — expect PASS (3).** Full suite green.
- [ ] **Step 5: Commit.** `git add scraper/theme.py tests/test_theme.py && git commit -m "feat(v4): brand theme (palette + app QSS) ported from chatbot"`

---

### Task 3: Ice-scraper window/exe icon

**Files:** Create `_make_scraper_icon.py` (repo root, one-off, matches `_make_icon.py` convention); produce `assets/scraper_icon.ico`; Test `tests/test_icon_asset.py`.

- [ ] **Step 1: Failing test.**
```python
# tests/test_icon_asset.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from PIL import Image

ICO = Path(__file__).parent.parent / "assets" / "scraper_icon.ico"

def test_icon_exists_and_valid():
    assert ICO.exists(), "run _make_scraper_icon.py to generate the icon"
    im = Image.open(ICO)
    assert im.format == "ICO"
    sizes = im.info.get("sizes") or {im.size}
    assert any(max(s) >= 64 for s in sizes), "icon must include a >=64px size"
```
- [ ] **Step 2: Run — expect FAIL (icon missing).**
- [ ] **Step 3: Write the generator + run it.**
```python
# _make_scraper_icon.py
"""One-off: draw a clean ice-scraper app mark (Contoso blue tile + white scraper glyph)
and save a multi-size .ico. Run: scraper\\venv\\Scripts\\python.exe _make_scraper_icon.py"""
from pathlib import Path
from PIL import Image, ImageDraw

BRAND = (81, 99, 158, 255)      # #51639e
WHITE = (255, 255, 255, 255)
S = 1024                         # supersample, then downscale

def draw() -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # rounded-square brand tile
    pad = S // 10
    d.rounded_rectangle([pad, pad, S - pad, S - pad], radius=S // 7, fill=BRAND)
    # ice-scraper: angled flat blade + handle (white)
    cx = S // 2
    # blade (a wide trapezoid near the lower-left, angled)
    d.polygon([(cx - 300, cx + 70), (cx + 120, cx + 70), (cx + 60, cx + 200), (cx - 240, cx + 200)], fill=WHITE)
    # blade lip
    d.rounded_rectangle([cx - 300, cx + 40, cx + 120, cx + 78], radius=18, fill=WHITE)
    # handle (rounded bar rising to upper-right)
    d.line([(cx + 20, cx + 120), (cx + 230, cx - 230)], fill=WHITE, width=70)
    d.ellipse([cx + 195, cx - 270, cx + 285, cx - 180], fill=WHITE)  # grip knob
    return im

def main() -> None:
    out = Path(__file__).parent / "assets" / "scraper_icon.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    big = draw()
    icon = big.resize((256, 256), Image.LANCZOS)
    icon.save(out, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {out}")

if __name__ == "__main__":
    main()
```
Run: `scraper\venv\Scripts\python.exe _make_scraper_icon.py`
- [ ] **Step 4: Run test — expect PASS.** (If Pillow lacks `rounded_rectangle.radius`, the venv's Pillow is modern enough — confirm; else use `rectangle`.)
- [ ] **Step 5: Commit.** `git add _make_scraper_icon.py assets/scraper_icon.ico tests/test_icon_asset.py && git commit -m "feat(v4): ice-scraper window/exe icon"`

---

### Task 4: `settings_dialog.py` — output folders + hidden credentials

**Files:** Create `scraper/settings_dialog.py`; Test `tests/test_settings_dialog.py`. Read first: `scraper/ticket_settings.py` (URL/username persist + keyring password), `scraper/app_settings.py`.

**Interfaces:**
- Produces: `class SettingsDialog(QDialog)` with: two folder rows (Tickets / KB) each a read-only `QLineEdit` + "Browse…" button, prefilled from `app_settings.tickets_dir()/kb_dir()`; a collapsible "Portal credentials" section (toggled by a button, hidden by default) with URL + username `QLineEdit` + masked password + "Save credentials" (writes URL/username via `ticket_settings.save`, password via `ticket_settings.save_password`); a Save/Close button row. `Save` persists output paths via `app_settings.save(...)`.
- Expose the path fields as attributes (`self.inp_tickets`, `self.inp_kb`, `self.cred_box`) for testing.

- [ ] **Step 1: Failing offscreen test.**
```python
# tests/test_settings_dialog.py
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
import scraper.app_settings as aps
from scraper.settings_dialog import SettingsDialog

_app = QApplication.instance() or QApplication([])

def test_dialog_constructs_and_prefills(tmp_path, monkeypatch):
    monkeypatch.setattr(aps, "tickets_dir", lambda: tmp_path / "tickets")
    monkeypatch.setattr(aps, "kb_dir", lambda: tmp_path / "kb")
    dlg = SettingsDialog()
    assert str(tmp_path / "tickets") in dlg.inp_tickets.text()
    assert str(tmp_path / "kb") in dlg.inp_kb.text()

def test_credentials_section_hidden_by_default():
    dlg = SettingsDialog()
    assert dlg.cred_box.isVisible() is False  # collapsed until expanded
```
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** `scraper/settings_dialog.py`. A `QDialog`: title "Settings"; output-folder rows (QLabel + read-only QLineEdit + Browse via `QFileDialog.getExistingDirectory`); a "▸ Portal credentials" toggle button that shows/hides `self.cred_box` (a QWidget, `setVisible(False)` initially) containing URL/username/password (password `setEchoMode(QLineEdit.Password)`) + "Save credentials" calling `ticket_settings.save` / `save_password`; bottom Save (persists `app_settings.save(inp_tickets, inp_kb)`) + Close. Apply no per-widget styles that fight the app QSS. Never log the password.
- [ ] **Step 4: Run — expect PASS (2).** Full suite green.
- [ ] **Step 5: Commit.** `git add scraper/settings_dialog.py tests/test_settings_dialog.py && git commit -m "feat(v4): Settings dialog (output folders + hidden portal credentials)"`

---

### Task 5: `app.py` shell — theme, animated splash, icon, Settings button

**Files:** Create `scraper/app.py`; Modify `scraper/gui.py` (add branded top bar + ⚙ Settings button; move `main()` to app.py); Test `tests/test_app_shell.py`. Read first: `Dev/kb_chatbot/gui.py` (`_make_splash`, `setMenuWidget` header, `AboutDialog`).

**Interfaces:**
- `app.py`: `main()` — `QApplication`, `app.setStyleSheet(theme.app_stylesheet())`, `app.setWindowIcon(QIcon(theme.asset_path("scraper_icon.ico")))`, build an animated branded `QSplashScreen` (logo on a white canvas via `theme.asset_file_url`/`QPixmap`; a short fade/"Starting…" message), show it, build `MainWindow`, `splash.finish(win)`, `win.show()`.
- `gui.py` `MainWindow`: add a brand top bar via `setMenuWidget(...)` (logo + "Contoso KB Scraper" + `v{APP_VERSION}` pill + a ⚙ Settings `QPushButton`), wire the Settings button to open `SettingsDialog(self).exec()`, set `self.setWindowIcon(...)`. Keep the existing tabs. Expose `self.btn_settings` for testing.

- [ ] **Step 1: Failing offscreen test.**
```python
# tests/test_app_shell.py
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import pytest
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
_app = QApplication.instance() or QApplication([])

def test_mainwindow_has_settings_button_and_icon():
    from scraper.gui import MainWindow
    win = MainWindow()
    assert hasattr(win, "btn_settings")
    assert win.windowIcon() is not None and not win.windowIcon().isNull()

def test_app_stylesheet_applies():
    from scraper import theme
    _app.setStyleSheet(theme.app_stylesheet())
    assert theme.PALETTE["brand"] in _app.styleSheet()
```
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** `app.py` + the `gui.py` top-bar/Settings additions (port the splash + header from the chatbot, adapt to the scraper). Keep imports light at module top.
- [ ] **Step 4: Run — expect PASS (2).** Full suite green.
- [ ] **Step 5: Commit.** `git add scraper/app.py scraper/gui.py tests/test_app_shell.py && git commit -m "feat(v4): themed app shell — splash, icon, branded top bar, Settings button"`

---

### Task 6: Phase 3 gate + offscreen UI shots + final review

- [ ] **Step 1:** Full suite green: `scraper\venv\Scripts\python.exe -m pytest tests/ -q`.
- [ ] **Step 2:** Capture offscreen screenshots of the themed `MainWindow` + `SettingsDialog` (a throwaway `_p3_ui_shots.py` setting `QT_QPA_PLATFORM=offscreen`, `widget.grab().save(png)`) for the user to review the look. (Offscreen renders text as tofu — layout/colour/objects are what we verify; note this to the user.)
- [ ] **Step 3:** Final whole-branch review of the Phase 3 diff (base = Phase-2 head `867a393`); fix Critical/Important, record Minor.
- [ ] **Step 4:** Update `.superpowers/sdd/progress.md` + memory; report Phase 3 complete + the recommended next phase.

---

## Self-Review
- **Spec coverage:** theme/look (T2, T5), splash + icon (T3, T5), Settings dialog with per-type output paths + hidden credentials (T1, T4). All from the v4 spec §7–§8. ✅
- **Placeholders:** pure modules (app_settings, theme, icon) carry full code; the two GUI tasks reference the chatbot source to port + define exact interfaces/attributes + offscreen tests. No vague steps. ✅
- **Type consistency:** `theme.PALETTE`/`app_stylesheet`/`asset_path` names match across T2/T5; `app_settings.tickets_dir()/kb_dir()/save()` match across T1/T4; `SettingsDialog` attrs (`inp_tickets`,`inp_kb`,`cred_box`) match across T4 tests + T5 usage. ✅
- **Note:** wiring the engines to *read* `app_settings` paths happens when the tabs are rewritten (Phases 4–5); this phase delivers the settings store + editor + themed shell. Output defaults keep current behavior unchanged.
