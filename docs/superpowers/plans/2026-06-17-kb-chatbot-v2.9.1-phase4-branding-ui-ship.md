# KB Chatbot v2.9.1 — Phase 4: Branding, UI Polish, Learn-Mode KDF, Version & Ship Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for Tasks 1-4 (deterministic, TDD). Tasks 5 (UI visual) and 6 (build) have explicit human-checkpoint steps — do NOT auto-complete them. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the app look enterprise-grade and properly branded (Contoso logo in header / welcome / About / splash + a cohesive theme), harden the Learn-Mode password (salted KDF), lock the chat-render XSS posture with a test, bump to v2.9.1, then reindex + build the shippable one-folder exe (with all of Phases 1-3 baked in).

**Architecture:** Mostly `Dev/kb_chatbot/gui.py` (theme, header, welcome, About, splash, render-helper extraction) + a new `assets/` folder (PNGs rasterized from the SVG) bundled via `ContosoKBChatbot.spec` + `Dev/kb_chatbot/settings.py` (KDF) + `config.py`/spec/.bat (version + build). No retrieval/orchestrator logic changes.

**Tech Stack:** Python 3, PySide6 (QtSvg for one-off rasterization), PyInstaller, pytest. Tests run with `scraper/venv/Scripts/python.exe -m pytest` from repo root.

## Global Constraints

- **Logo:** source `Contoso_Logo.svg` (297.5×70 wordmark). Pre-rasterize to PNG (no runtime SVG dependency); bundle via the spec; load freeze-aware (mirror the `HF_HOME`/`sys._MEIPASS` pattern already in `gui.py`).
- **Logo placement (all four):** header bar, welcome/empty state, About dialog, launch splash.
- **UI scope:** polish + layout tweaks — cohesive QSS theme (Segoe UI, consistent spacing/radius/contrast), restyled chat (message bubbles, off the monospace look), grouped controls. **No functional removals** (Learn Mode, attachments drag-drop/Ctrl+V, reindex, token-usage, settings, STOP, provider preflight all preserved). HTML-escaping in chat rendering preserved.
- **Visual sign-off:** the UI look (Task 5) is presented to the user via a screenshot of the running app and is NOT finalized without approval.
- **Build gate (standing rule):** NO exe compile without a smoke test + explicit user confirmation. Build into a **fresh `--workpath`** (NOT `--clean` — it triggers OneDrive `WinError 5`, per cerebrum); after `COLLECT --noconfirm`, re-copy the prebuilt index into `chatbot_state/`.
- **Security:** the KDF tightens auth; no secret introduced; nothing logged.
- **Test runner:** `scraper/venv/Scripts/python.exe -m pytest <path> -v` from repo root. Imports `from Dev.kb_chatbot...`.
- **Commit after each task.** Branch `feat/kb-chatbot-v2.9.1` (Phase 3 ends at `0a56c49`).

---

### Task 1: Logo assets — rasterize, bundle, freeze-aware loader

**Files:**
- Create: `_make_logo_pngs.py` (repo root, one-off rasterizer), `assets/contoso_logo.png`, `assets/contoso_logo_lg.png` (generated)
- Modify: `ContosoKBChatbot.spec` (add assets to `datas`), `Dev/kb_chatbot/gui.py` (add `_asset_path`)
- Test: `Dev/kb_chatbot/tests/test_assets.py` (new)

**Interfaces:**
- Produces: `gui._asset_path(name: str) -> Optional[str]` — absolute path to a bundled asset (frozen: `sys._MEIPASS/assets/<name>`; source: repo `assets/<name>`), or `None` if missing. Tasks 5 use it for the header/welcome/About/splash pixmaps.

- [ ] **Step 1: Write the one-off rasterizer and generate the PNGs**

Create `_make_logo_pngs.py`:

```python
"""One-off: rasterize Contoso_Logo.svg (297.5x70) to PNGs for in-app
branding. Run once: scraper/venv/Scripts/python.exe _make_logo_pngs.py"""
import sys
from pathlib import Path
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).parent
SVG = ROOT / "Contoso_Logo.svg"
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)
AR = 297.5 / 70.0  # aspect ratio


def render(out: Path, height: int):
    r = QSvgRenderer(str(SVG))
    w = int(round(height * AR))
    img = QImage(w, height, QImage.Format_ARGB32)
    img.fill(0)  # transparent
    p = QPainter(img)
    r.render(p, QRectF(0, 0, w, height))
    p.end()
    img.save(str(out), "PNG")
    print(f"wrote {out} ({w}x{height})")


app = QApplication(sys.argv)  # QImage/QPainter need a QApplication
render(ASSETS / "contoso_logo.png", 36)      # header height
render(ASSETS / "contoso_logo_lg.png", 96)   # welcome/splash/About
```

Run: `scraper/venv/Scripts/python.exe _make_logo_pngs.py`
Expected: prints two `wrote …` lines; `assets/contoso_logo.png` (~153x36) and `assets/contoso_logo_lg.png` (~408x96) exist.

- [ ] **Step 2: Write the failing test**

Create `Dev/kb_chatbot/tests/test_assets.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import gui


def test_asset_path_resolves_in_source_mode():
    p = gui._asset_path("contoso_logo.png")
    assert p is not None
    assert Path(p).exists()


def test_asset_path_missing_returns_none():
    assert gui._asset_path("no_such_asset_xyz.png") is None


def test_logo_pngs_committed():
    root = Path(gui.__file__).parent.parent.parent
    assert (root / "assets" / "contoso_logo.png").exists()
    assert (root / "assets" / "contoso_logo_lg.png").exists()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_assets.py -v`
Expected: FAIL (`gui` has no `_asset_path`).

- [ ] **Step 4: Implement `_asset_path` + bundle in spec**

In `Dev/kb_chatbot/gui.py`, add near the top (after the imports / `log` setup):

```python
def _asset_path(name: str):
    """Absolute path to a bundled asset. Frozen: <_MEIPASS>/assets/<name>;
    source: <repo>/assets/<name>. Returns None if the file is absent."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        cand = os.path.join(base, "assets", name)
    else:
        cand = os.path.join(str(Path(__file__).parent.parent.parent), "assets", name)
    return cand if os.path.isfile(cand) else None
```

In `ContosoKBChatbot.spec`, after the `datas, binaries, hiddenimports = [], [], []` line (before/after the package loop), add the assets to `datas`:

```python
import os as _os2
_assets_dir = _os2.path.join(_os2.path.dirname(_os2.path.abspath(SPEC)), "assets") \
    if "SPEC" in dir() else "assets"
for _png in ("contoso_logo.png", "contoso_logo_lg.png"):
    _ap = _os2.path.join("assets", _png)
    if _os2.path.isfile(_ap):
        datas.append((_ap, "assets"))
```

(If `SPEC` is not available in this PyInstaller version, the relative `"assets"` path works because PyInstaller runs from the spec's directory.)

- [ ] **Step 5: Run test to verify it passes, then commit**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_assets.py -v`
Expected: PASS.

```bash
git add _make_logo_pngs.py assets/contoso_logo.png assets/contoso_logo_lg.png ContosoKBChatbot.spec Dev/kb_chatbot/gui.py Dev/kb_chatbot/tests/test_assets.py
git commit -m "feat(v2.9.1): rasterize Contoso logo PNGs, bundle in spec, freeze-aware _asset_path"
```

---

### Task 2: Learn-Mode password — salted KDF + constant-time compare

**Files:**
- Modify: `Dev/kb_chatbot/settings.py`
- Test: `Dev/kb_chatbot/tests/test_learn_mode.py`

**Interfaces:**
- Produces: `settings.hash_password(password: str) -> str` (format `pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>`); `check_learn_password` verifies BOTH the new format and the legacy bare-SHA-256 hash (backward compat), using `hmac.compare_digest`.

- [ ] **Step 1: Write the failing tests**

Append to `Dev/kb_chatbot/tests/test_learn_mode.py`:

```python
from Dev.kb_chatbot.settings import hash_password, check_learn_password
import hashlib

def test_hash_password_pbkdf2_format_roundtrips():
    h = hash_password("hunter2")
    assert h.startswith("pbkdf2_sha256$")
    assert check_learn_password("hunter2", h) is True
    assert check_learn_password("wrong", h) is False

def test_hash_password_salts_are_random():
    assert hash_password("same") != hash_password("same")  # per-call random salt

def test_check_legacy_sha256_still_verifies():
    legacy = hashlib.sha256("oldpw".encode()).hexdigest()
    assert check_learn_password("oldpw", legacy) is True
    assert check_learn_password("nope", legacy) is False

def test_check_empty_password_rejected():
    assert check_learn_password("", hash_password("x")) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_learn_mode.py -k "pbkdf2 or legacy or salts or empty_password" -v`
Expected: FAIL (`hash_password` undefined).

- [ ] **Step 3: Implement the KDF**

In `Dev/kb_chatbot/settings.py`, add `import hmac` and `import os` at the top, and replace `check_learn_password` (and add `hash_password`):

```python
_PBKDF2_ITERS = 200_000

def hash_password(password: str) -> str:
    """Salted PBKDF2-HMAC-SHA256. Returns 'pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>'."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERS)
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"

def check_learn_password(candidate: str, stored_hash: str) -> bool:
    """Verify a Learn-Mode password against the stored hash. Supports the new
    salted PBKDF2 format and the legacy bare-SHA-256 hash (backward compat).
    Constant-time comparison via hmac.compare_digest."""
    if not candidate or not stored_hash:
        return False
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iters_s, salt_hex, hash_hex = stored_hash.split("$")
            dk = hashlib.pbkdf2_hmac("sha256", candidate.encode(),
                                     bytes.fromhex(salt_hex), int(iters_s))
            return hmac.compare_digest(dk.hex(), hash_hex)
        except (ValueError, TypeError):
            return False
    # Legacy bare SHA-256 (so existing installs aren't locked out)
    return hmac.compare_digest(hashlib.sha256(candidate.encode()).hexdigest(), stored_hash)
```

(Leave `DEFAULT_LEARN_MODE_HASH` as the legacy SHA-256 of the shipped default — the legacy branch verifies it, so the app works out of the box; any password a user sets via `hash_password` uses the strong KDF. A change-password UI + forced rotation off the default is a documented follow-up, not in this task.)

- [ ] **Step 4: Run tests to verify they pass, then commit**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_learn_mode.py -v`
Expected: PASS (new + all pre-existing learn-mode tests — the existing `check_learn_password_correct/wrong/empty` cases use the legacy hash, still handled by the legacy branch).

```bash
git add Dev/kb_chatbot/settings.py Dev/kb_chatbot/tests/test_learn_mode.py
git commit -m "feat(v2.9.1): salted PBKDF2 Learn-Mode password hash + constant-time compare (legacy-compatible)"
```

---

### Task 3: Chat-render XSS regression test (extract a pure helper)

**Files:**
- Modify: `Dev/kb_chatbot/gui.py` (extract the HTML builder from `_append`)
- Test: `Dev/kb_chatbot/tests/test_render.py` (new)

**Interfaces:**
- Produces: `gui._build_message_html(role: str, text: str, colour: str, tag: str, ts: str) -> str` — the escape-then-linkify HTML builder, used by `MainWindow._append`. Pure (no Qt widget needed), so it is unit-testable.

- [ ] **Step 1: Write the failing test**

Create `Dev/kb_chatbot/tests/test_render.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import gui


def test_render_escapes_html_in_text():
    out = gui._build_message_html("ai", "<img src=x onerror=alert(1)>", "#000", "AI:", "12:00:00")
    assert "<img" not in out
    assert "&lt;img" in out


def test_render_only_links_http_urls():
    out = gui._build_message_html("ai", "see [x](javascript:alert(1)) and [y](https://help.contoso.example/p)",
                                  "#000", "AI:", "12:00:00")
    assert 'href="javascript:' not in out
    assert 'href="https://help.contoso.example/p"' in out


def test_render_malicious_title_is_inert():
    out = gui._build_message_html("ai", '[<b>boom</b>](https://help.contoso.example/p)', "#000", "AI:", "12:00:00")
    assert "<b>boom</b>" not in out  # title is escaped before linkify
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_render.py -v`
Expected: FAIL (`gui` has no `_build_message_html`).

- [ ] **Step 3: Extract the pure builder**

In `Dev/kb_chatbot/gui.py`, add a module-level function that contains the exact escape-then-linkify logic currently inside `MainWindow._append`:

```python
def _build_message_html(role: str, text: str, colour: str, tag: str, ts: str) -> str:
    safe_text = html_module.escape(text)
    if role == "ai":
        safe_text = _LINK_RE.sub(r'<a href="\2">\1</a>', safe_text)
    safe_text = safe_text.replace("\n", "<br>")
    return (
        f'<p style="margin:4px 0; font-family:Consolas,monospace; font-size:10pt;">'
        f'<span style="color:#555;">{ts}</span> '
        f'<b style="color:{colour};">{html_module.escape(tag)}</b> '
        f'<span style="color:{colour};">{safe_text}</span>'
        f'</p>'
    )
```

Then change `MainWindow._append` to call it (preserving current behavior):

```python
    def _append(self, role: str, text: str, colour: str, tag: str):
        ts = datetime.now().strftime("%H:%M:%S")
        block = _build_message_html(role, text, colour, tag, ts)
        self.chat_view.append(block)
        self.chat_view.ensureCursorVisible()
```

(The inline `<p>` style here is rewritten in Task 5's theme; this task only extracts + tests the escaping/linkify. `_LINK_RE` already requires `https?://`, so `javascript:` links never match.)

- [ ] **Step 4: Run test to verify it passes, then commit**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_render.py -v`
Expected: PASS.

```bash
git add Dev/kb_chatbot/gui.py Dev/kb_chatbot/tests/test_render.py
git commit -m "test(v2.9.1): extract _build_message_html + lock escape-before-linkify / http(s)-only rendering"
```

---

### Task 4: Version bump to 2.9.1 + fix the build command

**Files:**
- Modify: `Dev/kb_chatbot/config.py` (`APP_VERSION`), `build_chatbot_exe.bat` (drop `--clean`, use fresh `--workpath`)
- Test: `Dev/kb_chatbot/tests/test_version.py`

**Interfaces:** `config.APP_VERSION == "2.9.1"`.

- [ ] **Step 1: Write the failing test**

Replace the assertion in `Dev/kb_chatbot/tests/test_version.py`'s `test_app_version_is_2_8` with a renamed test:

```python
def test_app_version_is_2_9_1():
    from Dev.kb_chatbot import config
    assert config.APP_VERSION == "2.9.1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_version.py -v`
Expected: FAIL (APP_VERSION is "2.8").

- [ ] **Step 3: Bump version + fix build script**

In `Dev/kb_chatbot/config.py`: `APP_VERSION = "2.9.1"`.

In `build_chatbot_exe.bat`, change the PyInstaller line from `--clean --noconfirm` to a fresh workpath (avoids the OneDrive `WinError 5` from `--clean` deleting a locked tree):

```bat
"scraper\venv\Scripts\python.exe" -m PyInstaller ContosoKBChatbot.spec --workpath build_v291 --noconfirm
```

Update the echoed artifact path to `dist\ContosoKBChatbot-v2.9.1\ContosoKBChatbot-v2.9.1.exe`.

- [ ] **Step 4: Run test to verify it passes, then commit**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_version.py -v`
Expected: PASS.

```bash
git add Dev/kb_chatbot/config.py build_chatbot_exe.bat Dev/kb_chatbot/tests/test_version.py
git commit -m "chore(v2.9.1): bump APP_VERSION to 2.9.1; build into fresh --workpath (avoid OneDrive WinError 5)"
```

---

### Task 5: UI theme + branding placement (VISUAL — requires user sign-off)

**Files:**
- Modify: `Dev/kb_chatbot/gui.py` (QSS theme in `main()`; header widget; welcome/empty state; `AboutDialog` + Help action; `QSplashScreen`; restyle `_build_message_html` + control bar)
- Test: smoke construction test in `Dev/kb_chatbot/tests/test_render.py` where feasible (offscreen)

**This task is NOT auto-completed. It is implemented as a draft, screenshotted, and approved by the user before commit.**

- [ ] **Step 1: Implement the theme + branding (draft)**
  - Apply an app-wide QSS theme in `main()` via `app.setStyleSheet(...)`: Segoe UI base font; an enterprise palette (derive the accent from the Contoso logo's brand color — extract the dominant fill from `Contoso_Logo.svg`); consistent control padding/border-radius; WCAG-aware contrast. Centralize colors as module constants so the ad-hoc inline `setStyleSheet` calls (feedback bar, correction panel, attachment chips) read from the palette.
  - **Header bar:** a top widget above the controls row — `QLabel` with the header logo pixmap (`_asset_path("contoso_logo.png")`) + "Contoso KB Assistant" + `v{config.APP_VERSION}`.
  - **Welcome/empty state:** before the first message, show the large logo (`contoso_logo_lg.png`) centered in the chat area with a one-line hint; replaced on first turn.
  - **About dialog:** new `AboutDialog` (large logo, `v{APP_VERSION}`, provider/CLI status) opened from a new **Help → About** toolbar action.
  - **Splash:** a `QSplashScreen` with the large logo shown in `main()` before the window builds; closed on init-ready.
  - **Chat restyle:** rework `_build_message_html` to message-bubble styling (user vs AI vs system) off the monospace look — KEEP the escape-then-linkify logic from Task 3 intact (the regression test must still pass).
  - Preserve every existing handler/feature.

- [ ] **Step 2: Smoke-construct test (offscreen)**

Add to `Dev/kb_chatbot/tests/test_render.py` (guarded so it skips if Qt can't init offscreen):

```python
import os
def test_about_dialog_and_header_construct(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from Dev.kb_chatbot import gui
    # AboutDialog constructs without error and shows the version
    dlg = gui.AboutDialog(None)
    assert config_version_in(dlg)  # helper: asserts v2.9.1 text present
```

(Adjust to the actual `AboutDialog` API; if full construction needs a parent MainWindow, test the smaller helpers instead. Keep it green or skipped, never failing.)

- [ ] **Step 3: Run the app + capture a screenshot**

Launch the app from source and capture screenshots of: the splash, the welcome/empty state, a Q&A exchange, and the About dialog. (Qt: `widget.grab().save("…png")`, or run `scraper/venv/Scripts/python.exe Dev/kb_chatbot/gui.py` and screenshot.) Save to `.wolf/designqc-captures/` or a temp path.

- [ ] **Step 4: HUMAN CHECKPOINT — present screenshots, get sign-off**

Show the user the screenshots. Iterate on palette/spacing/layout until they approve the look. **Do not commit Task 5 until the user approves.**

- [ ] **Step 5: Run the focused render + asset tests, then commit (after approval)**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_render.py Dev/kb_chatbot/tests/test_assets.py -v`
Expected: PASS (escaping regression intact).

```bash
git add Dev/kb_chatbot/gui.py Dev/kb_chatbot/tests/test_render.py
git commit -m "feat(v2.9.1): enterprise UI theme + Contoso branding (header/welcome/About/splash)"
```

---

### Task 6: Reindex + smoke test + build (GATED — user OK before compile)

**Files:** runtime/build only (no source changes beyond what Tasks 1-5 committed).

**This task is NOT auto-completed. The exe compile requires a passing smoke test + explicit user confirmation (standing rule).**

- [ ] **Step 1: Full regression suite (green gate)**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests -v`
Expected: ALL pass (Phases 1-4). Fix any regression before continuing.

- [ ] **Step 2: Reindex from source (bakes in Phases 1-2)**

The `CHUNK_SCHEMA_VERSION` bump (Phase 1) auto-forces a full re-embed. Run an ingest over the real `library/` into the dev `state/chroma` (the app's reindex path / `ingest(..., force_rebuild=True)`), then run the extended secret probe to confirm the new index is clean:

Run: `scraper/venv/Scripts/python.exe _v291_secret_probe.py`
Expected: `leaks=0`.

- [ ] **Step 3: Source smoke test (both providers)**

Launch the app from source. Verify on BOTH Claude and GPT-5.4: (a) a ticket question returns the full resolution + root cause + KB link (if any) + screenshot note; (b) the same question twice is consistent; (c) a clearly-unrelated question → "outside scope"; (d) GPT-5.4 token usage is visibly lower (reasoning) in the Token Usage dialog; (e) branding (header/welcome/About/splash) renders. Record results.

- [ ] **Step 4: HUMAN CHECKPOINT — confirm before compile**

Present the smoke-test results to the user. **Only compile after explicit approval.**

- [ ] **Step 5: Build the exe (after approval)**

Run: `build_chatbot_exe.bat` (now uses fresh `--workpath build_v291`). After `COLLECT`, re-copy the prebuilt index into `dist/ContosoKBChatbot-v2.9.1/chatbot_state/chroma/` (per the ship-prebuilt-index pattern). Launch the built exe; confirm version `2.9.1` in title/About, branding shows, and a ticket question answers correctly with the shipped index.

- [ ] **Step 6: Commit any build-doc updates + finalize**

```bash
git add -A && git commit -m "build(v2.9.1): reindex + ship one-folder exe (Phases 1-4)"
```

---

## Self-Review

**Spec coverage (Phase 4 = spec §6.3, §6.4, §6.5d, §6.5e, §6.6):**
- §6.3 logo/branding (assets + header + welcome + About + splash) → Task 1 + Task 5. ✓
- §6.4 UI polish + layout (QSS theme, chat restyle, control bar) → Task 5. ✓
- §6.5(d) Learn-Mode KDF → Task 2 (PBKDF2 + compare_digest + legacy compat). ✓ (forced-rotation-off-default + change-pw UI noted as a follow-up — no UI exists today.)
- §6.5(e) rendering regression test → Task 3. ✓
- §6.6 version + reindex + build → Task 4 + Task 6 (fresh `--workpath`, re-copy index, version 2.9.1). ✓

**Placeholder scan:** Tasks 1-4 have complete code/commands. Tasks 5-6 are intentionally checkpoint-structured (visual sign-off / build gate) — the UI's exact palette/layout is deliberately left to the screenshot-iteration loop with the user (the spec made the look subject to approval), and the smoke-test scenarios are enumerated. This is not a placeholder; it is a required human gate.

**Type consistency:** `_asset_path` (Task 1) consumed by Task 5; `hash_password`/`check_learn_password` (Task 2) self-consistent; `_build_message_html` (Task 3) reused+restyled in Task 5 with the escaping preserved (Task 3's test guards it); `config.APP_VERSION="2.9.1"` (Task 4) drives the spec exe name + About/header/title.

**Risks:** (1) UI restyle could regress a handler — mitigated by preserving all signals + the render regression test + the smoke test. (2) `--clean`→`--workpath` is the known OneDrive fix. (3) Reindex is slow (full corpus) — run once at ship. (4) Offscreen Qt construct-test may be environment-flaky — guarded to skip, never fail. (5) The KDF leaves the public default working (no forced rotation without a change-pw UI) — documented; low risk (gates KB-write only).
