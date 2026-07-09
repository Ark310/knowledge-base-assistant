# KB Chatbot v3.0.1 — Phase 6: Web UI (QtWebEngine + build-free front-end) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. **When authoring the HTML/CSS visual layer (Tasks 4-7), first invoke the `frontend-design` skill** to hit the Anthropic-quality look; validate with `openwolf designqc`.

**Goal:** Replace the QTextBrowser chat surface with an embedded QtWebEngine web UI — an Anthropic `customer-support-agent`-inspired, Contoso-branded layout (top config bar, left chat-history sidebar, center chat, right Sources + thinking/debug panel) — driven by a single QWebChannel bridge over the existing engine. Wire the Phase 3 provider selector + first-run onboarding. Keep the heavy Qt dialogs (reindex progress, token-usage) as native windows launched from the web UI.

**Architecture:** A single `ChatBridge(QObject)` exposes `@Slot` methods + `Signal`s to JavaScript via `QWebChannel`. `gui.MainWindow` hosts a `QWebEngineView` loading a **build-free** local page (`webui/index.html` + hand-authored CSS + vanilla JS; markdown rendered client-side with vendored `marked` + `DOMPurify` for XSS safety — no Node build, fully offline). Turns run off-thread by **reusing the existing `TurnWorker`** pattern; results come back as a `Signal`. The Python engine (Retriever, orchestrator, `factory.make_provider`, Session, settings, `local_creds`, `onboarding`) is unchanged — only the presentation + a thin bridge are added. `IndexingDialog` + `TokenUsageDialog` stay as Qt windows opened via bridge slots.

**Tech Stack:** PySide6 6.11 (QtWebEngineWidgets + QtWebChannel — already installed), vanilla JS + hand CSS, vendored `marked.min.js` + `purify.min.js` (offline), pytest for bridge logic (mocked; no live webview).

## Global Constraints

- **QtWebEngine init order:** `QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)` MUST run before `QApplication(...)` is constructed (gui.py `main()` L1605-1606). Import `PySide6.QtWebEngineWidgets` at module top so the engine initializes.
- **Offline / no CDN:** every asset (JS, CSS, fonts, logo, marked, DOMPurify) is bundled and referenced locally (the exe has no internet and a strict-offline posture). No external `<script src=…>`/`<link href=…>` to the web.
- **XSS:** answer HTML is produced by `marked` then **`DOMPurify.sanitize`** before insertion; citation/link clicks are intercepted and opened in the system browser (never navigated inside the webview). This preserves the v2.9.1 XSS guarantee.
- **Single bridge:** exactly one `ChatBridge` object registered on the channel as `bridge`. JS↔Python payloads are JSON strings (slots return `str`; signals carry `str`).
- **Reuse threading:** turns run via the existing `TurnWorker(QThread)` + `WorkerSignals` (gui.py L240-272) — do NOT block the GUI/WebEngine thread.
- **Provider construction goes through `factory.make_provider(provider_id, settings)`** (Phase 3) — replaces the old `build_provider` (L218-225) so the Local provider works.
- **Brand:** Contoso palette (`gui.PALETTE` L85-111) + logo assets (`assets/contoso_logo*.png`); keep the splash. Drop the demo's "user mood" panel.
- **Keep working dialogs:** `IndexingDialog` (L533-655) + `TokenUsageDialog` (L472-530) stay Qt, launched via bridge slots. Learn Mode moves into the web UI.
- **State:** call `config.migrate_state_if_needed(config._LEGACY_STATE)` once at startup (Phase 2 migration) before the engine opens the index.
- **No APP_VERSION bump here** (that's Phase 7). Tests: bridge logic unit-tested with a fake engine; visual QC via designqc.

## File Structure

- Create: `Dev/kb_chatbot/bridge.py` — `ChatBridge(QObject)` (the entire JS API).
- Create: `Dev/kb_chatbot/webui/index.html`, `webui/styles.css`, `webui/app.js`, `webui/vendor/marked.min.js`, `webui/vendor/purify.min.js`, `webui/assets/` (copied logo).
- Create: `Dev/kb_chatbot/chat/history.py` — chat persistence (save/list/load/rename/delete/search + auto-title).
- Modify: `Dev/kb_chatbot/gui.py` — `main()` (AA attribute), `MainWindow._build_ui` (swap QTextBrowser → QWebEngineView + channel), `_send`/`_on_turn_done` re-routed through the bridge, retire the Qt controls-bar/toolbar chat bits (keep reindex/usage dialogs).
- Tests: `Dev/kb_chatbot/tests/test_bridge.py`, `test_history.py`, `test_webui_assets.py`.

---

### Task 1: QtWebEngine shell + stub bridge (app boots, page loads, channel talks)

**Files:** modify `gui.py`; create `webui/index.html`, `webui/app.js`, `webui/styles.css`, `bridge.py` (stub); test `tests/test_webui_assets.py`.

**Interfaces:**
- Produces: `bridge.ChatBridge` (stub with `@Slot(result=str) ping()` returning `"pong"`); `gui._webui_dir()` → Path; a `QWebEngineView` in `MainWindow` loading `index.html` with a `QWebChannel` exposing `bridge`.

- [ ] **Step 1: Add the QtWebEngine attribute + import (gui.py)**

At gui.py module top, add:
```python
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebChannel import QWebChannel
```
In `main()`, BEFORE `app = QApplication(sys.argv)`:
```python
    from PySide6.QtCore import Qt
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
```

- [ ] **Step 2: Add `_webui_dir()` + a nav-intercepting page**

```python
def _webui_dir() -> Path:
    return Path(__file__).parent / "webui"

class _ChatPage(QWebEnginePage):
    """Open http(s) links in the system browser; keep local navigation in-app."""
    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if url.scheme() in ("http", "https"):
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(url)
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)
```

- [ ] **Step 3: Write the stub `bridge.py`**

```python
"""Single QWebChannel bridge between the web UI (JS) and the Python engine."""
from __future__ import annotations
from PySide6.QtCore import QObject, Slot


class ChatBridge(QObject):
    def __init__(self, window=None) -> None:
        super().__init__()
        self._window = window

    @Slot(result=str)
    def ping(self) -> str:
        return "pong"
```

- [ ] **Step 4: Write a minimal `webui/index.html` + `app.js` + `styles.css`**

`index.html` (loads qwebchannel.js from Qt's resource, then app.js):
```html
<div id="app"><div id="boot">Loading…</div></div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script src="app.js"></script>
```
`app.js`:
```javascript
window.bridge = null;
new QWebChannel(qt.webChannelTransport, (channel) => {
  window.bridge = channel.objects.bridge;
  bridge.ping().then((r) => { document.getElementById("boot").textContent = "bridge: " + r; });
});
```
`styles.css`: minimal reset + `#boot{font:14px system-ui;padding:2rem;}` (real styling lands in Task 3+).

- [ ] **Step 5: Swap the chat surface in `MainWindow._build_ui`**

Replace the `self.chat_view = QTextBrowser()` block (L875-880) with:
```python
        self.chat_view = QWebEngineView()
        self.chat_view.setPage(_ChatPage(self.chat_view))
        self.bridge = ChatBridge(self)
        self._channel = QWebChannel()
        self._channel.registerObject("bridge", self.bridge)
        self.chat_view.page().setWebChannel(self._channel)
        self.chat_view.setUrl(QUrl.fromLocalFile(str(_webui_dir() / "index.html")))
```
(Add `from PySide6.QtCore import QUrl` and `from Dev.kb_chatbot.bridge import ChatBridge` at top. Leave the rest of `_build_ui` for now; Task 3 removes the now-redundant Qt controls bar + input row.)

- [ ] **Step 6: Test — assets exist + reference correctly**

```python
# tests/test_webui_assets.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot import gui

def test_webui_files_exist():
    d = gui._webui_dir()
    for f in ("index.html", "app.js", "styles.css"):
        assert (d / f).exists(), f
    html = (d / "index.html").read_text(encoding="utf-8")
    assert "qwebchannel.js" in html and "app.js" in html

def test_bridge_ping():
    from Dev.kb_chatbot.bridge import ChatBridge
    assert ChatBridge().ping() == "pong"
```

- [ ] **Step 7: Run + manual boot check**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_webui_assets.py -v` → PASS.
Manual (operator, once): launch the app; the window shows "bridge: pong" → QtWebEngine + channel work.

- [ ] **Step 8: Commit** — `feat(v3.0.1-p6): QtWebEngine shell + QWebChannel stub bridge`

---

### Task 2: `ChatBridge` core — send a turn through the engine (reuse TurnWorker)

**Files:** `bridge.py`; `tests/test_bridge.py`.

**Interfaces:**
- Consumes: `factory.make_provider`, `orchestrator.handle_turn`/`Deps`, `Session`, `Filters`, settings, the window's `_retriever`.
- Produces on `ChatBridge`:
  - `Signal answerReady(str)` — JSON `{kind, markdown, citations:[{raw,verified}], sources:[…], debug:{…}, chat_id}`.
  - `Signal turnFailed(str)`, `Signal turnProgress(str)`.
  - `@Slot(str, str) send_message(text, product)` — starts a `TurnWorker`; non-blocking.
  - `@Slot() stop()` — cancels the running worker.
  - `@Slot(result=str) providers()` — JSON of `config.PROVIDERS` for the selector.
  - Pure helper `_answer_payload(turn) -> dict` (unit-tested).

- [ ] **Step 1: Write the failing test (payload shaping is pure + testable)**

```python
# tests/test_bridge.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.bridge import ChatBridge
from Dev.kb_chatbot.chat.session import Turn
from Dev.kb_chatbot.chunker import Chunk

def test_answer_payload_shapes_turn():
    turn = Turn(role="assistant", kind="answer", content="Fixed it. [Ticket #1](u)",
                citations=[{"raw": "[Ticket #1](u)", "verified": True}],
                retrieved_ids=["ticket_1"], model="m", tokens_in=10, tokens_out=5, latency_ms=100)
    ctx = [Chunk(id="ticket_1", text="...", metadata={"kind": "ticket", "ticket_id": "1",
                 "title": "Ticket #1", "url": "u", "product": "tradedesk", "created_at": "2024-01-01"})]
    p = ChatBridge._answer_payload(turn, ctx)
    assert p["kind"] == "answer"
    assert p["markdown"].startswith("Fixed it")
    assert p["sources"][0]["ticket_id"] == "1" and p["sources"][0]["url"] == "u"
    assert p["debug"]["tokens_out"] == 5

def test_providers_json_has_local():
    d = json.loads(ChatBridge().providers())
    assert "local" in d and d["local"]["default_model"] == "contoso-reasoning-qwen25-7b"
```

- [ ] **Step 2: Implement the core bridge** (full code — signals, send_message via TurnWorker, payload shaping). See the task's code block; key points: `send_message` reads live provider/model/gateway from settings, builds `Deps` via `factory.make_provider`, spawns `TurnWorker` (imported from `gui`), connects its signals to emit `answerReady`/`turnFailed`/`turnProgress`; `_answer_payload(turn, ctx)` maps `turn` + the turn's context chunks to `{kind, markdown, citations, sources[], debug}` where each source = `{kind, ticket_id/title, url, product, created_at, resolved}` from chunk metadata.

- [ ] **Step 3-5:** Run tests → PASS; wire `send_message` to the window's `_retriever`/session; commit `feat(v3.0.1-p6): ChatBridge core — turn dispatch + answer payload`.

---

### Task 3: Web chat surface + top config bar (the main visible UI)

**REQUIRED: invoke `frontend-design` skill first**, then author `index.html`/`styles.css`/`app.js` to the layout spec below; validate with `openwolf designqc`.

**Layout spec (Anthropic-inspired, Contoso-branded):**
- **Top bar:** Contoso logo (left); center/right = provider `<select>` + model `<select>` + product `<select>` + per-provider readiness dot; "New chat" button. Uses `bridge.providers()` + `bridge.provider_status()`; on change calls `bridge.set_provider/set_model`.
- **Center:** message list (user right / assistant left bubbles, real CSS flexbox now), markdown rendered via vendored `marked` + `DOMPurify.sanitize`, inline citation links (open via the nav interceptor), a "thinking…" indicator on `turnProgress`, and the composer (textarea + send + attach + stop). `send_message` on submit; render on `answerReady`.
- Streaming: current engine returns the full answer (no token stream) — show the thinking indicator until `answerReady`, then render. (Keep the door open for future streaming.)

- [ ] Vendor `marked.min.js` + `purify.min.js` into `webui/vendor/` (offline copies).
- [ ] Author the page + wire all bridge calls/signals; empty-state = Contoso welcome.
- [ ] Remove the now-redundant Qt controls bar (L844-873) + input row (L921-938) from `_build_ui` (chat + config now live in the page); keep the toolbar actions that open Qt dialogs (reindex, usage) — or move them to bridge slots in Task 6.
- [ ] `openwolf designqc` capture + review vs the reference; iterate. Commit.

---

### Task 4: Left history sidebar + chat persistence (`chat/history.py`)

**Interfaces:** `history.py` — `save(session, chat_id=None) -> chat_id`, `list_chats() -> list[dict]` (id, title, ts), `load(chat_id) -> dict`, `rename(chat_id, title)`, `delete(chat_id)`, `search(q) -> list[dict]`, `auto_title(session) -> str` (ticket # if referenced, else first-question topic). Stored as JSON under `config.CHATS_DIR` (now off OneDrive). Bridge slots: `new_chat/list_chats/load_chat/rename_chat/delete_chat/search_chats`.

- [ ] TDD `test_history.py` (save/list/load/rename/delete/search + auto_title picks ticket # when present else a trimmed topic). Web: left sidebar list + search box + rename/delete affordances + "New chat". Commit.

---

### Task 5: Right Sources panel + collapsible thinking/debug

**Interfaces:** the `answerReady` payload already carries `sources[]` + `debug{}`. Web renders a right panel: **Sources** = the tickets/KB behind the answer (title, id, date, product, link) ; **Thinking/Debug** (collapsible, hidden by default) = retrieval scores + classification + latency + tokens. Bridge adds `@Slot(result=str) last_sources()` for re-open.

- [ ] Render both panels; toggle; wire to `answerReady`. designqc pass. Commit.

---

### Task 6: Settings + onboarding wizard in web; keep reindex/usage as Qt

**Interfaces (bridge slots):** `get_settings()/save_settings(json)` (KB source, default provider/model, confidence, gateway URL/username); `set_gateway_password(pw)` → `local_creds.set_password`; `onboarding_check(provider)`/`onboarding_install(provider)`/`onboarding_login(provider)` (call the Phase 3 `onboarding` module; installs/logins via `run_visible`); `open_reindex()`/`open_usage()` → open the existing `IndexingDialog`/`TokenUsageDialog`; `learn_unlock(pw)->bool`/`learn_submit(json)->bool` (existing learn-mode logic).

- [ ] TDD the bridge slots (mock `onboarding`, `local_creds`, settings). Web: a Settings modal + a first-run onboarding wizard (shows each provider's readiness from `onboarding_check`, buttons to install/login, a gateway URL/user/password form). Reindex + usage open the Qt dialogs. Commit.

---

### Task 7: Branding, splash, About, state migration, polish

- [ ] Contoso logo in the top bar + welcome; keep `_make_splash()`; About → a web modal (or keep the Qt `AboutDialog` via a bridge slot). Call `config.migrate_state_if_needed(config._LEGACY_STATE)` at startup before the engine opens the index. Final `openwolf designqc` pass across light/dark; fix spacing/contrast. Commit.

---

### Task 8: Full regression + verification

- [ ] `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/ -q` → all pass (new bridge/history/asset tests + prior suite; the old `test_render.py` QTextBrowser-bubble tests are removed/replaced since the surface is gone — migrate their XSS intent to a DOMPurify note + a bridge sanitize test).
- [ ] Manual (operator): launch, send a question on each available provider, confirm citations open in the browser, history save/rename/search, Sources panel, Settings + onboarding readiness dots, reindex + usage dialogs open.
- [ ] `openwolf designqc` final capture. Commit.

## Self-Review (completed)
- **Spec coverage (spec §6.6):** QtWebEngine-in-PySide6 ✓ (T1), single bridge ✓ (T2), top config bar+selector ✓ (T3), left history (save/rename/auto-name/search) ✓ (T4), center chat (markdown+citations, sanitized) ✓ (T3), right Sources + collapsible thinking/debug ✓ (T5), Settings+onboarding wizard in web + reindex/usage stay Qt ✓ (T6), branding/splash/state-migration ✓ (T7). "User mood" dropped ✓. Build-free + offline + factory.make_provider ✓ (constraints).
- **QtWebEngine gotchas handled:** AA_ShareOpenGLContexts before QApplication (T1); nav interceptor for external links (T1); reuse TurnWorker off-thread (T2). 
- **Placeholders:** the visual CSS/HTML is intentionally delegated to the `frontend-design` skill at execution with an explicit layout spec + the exact bridge API each piece calls + designqc acceptance — appropriate for a creative UI layer; all Python (bridge, history, gui integration) is specified concretely.
- **Risk:** QtWebEngine adds ~150 MB to the exe (Phase 7 packaging note) + needs its resources bundled by PyInstaller (`--collect-all PySide6` or the QtWebEngine data) — flagged for Phase 7.
```
