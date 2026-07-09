# KB Chatbot v3.0.1 — Phase 3: Reasoning Backends + Onboarding + Local Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third, on-prem reasoning provider (the fine-tuneable Local model behind the AI-PC gateway) as a first-class selectable backend alongside Claude and Codex, and add fully-automatic first-run onboarding (detect → install → login) so the exe self-provisions on a colleague's machine.

**Architecture:** A new `LocalProvider` implements the existing `LLMProvider.chat(...)` interface by POSTing to the AI-PC gateway's OpenAI-compatible `/v1/chat/completions` route with HTTP Basic auth (temperature 0 + fixed seed → true determinism). A `make_provider(provider_id)` factory centralizes provider construction. Per-user gateway credentials live in the OS keyring; the gateway URL lives in settings. An `onboarding` package detects each provider's readiness and returns the exact install/login commands (Claude = native winget/PS installer, no Node; Codex = Node + npm `@openai/codex`; Local = URL + creds only), run in a visible console. GUI wiring of the selector + first-run wizard is deferred to Phase 6; this phase delivers the backend + a headless live-smoke the operator runs against the live gateway.

**Tech Stack:** Python 3.12, `urllib` (stdlib, no new HTTP dep), `keyring` (already used by the scraper), pytest with mocks (no network in unit tests).

## Global Constraints

- **Providers are account/creds-based — NO provider API keys stored** (org policy). Claude/Codex use their CLI OAuth login; Local uses gateway Basic-auth creds in the **keyring** (never in JSON/logs). Gateway **password is never logged or written to disk** outside the keyring.
- **Determinism:** Local calls send `temperature=0`, `seed=42`, `stream=false`.
- **Windows subprocess:** the app monkeypatches `subprocess.Popen` to add `CREATE_NO_WINDOW` (hidden). Interactive install/login MUST be visible, so onboarding launches them via `cmd /c start "" ...` (a new visible console), not a bare hidden Popen.
- **Codex** stays pinned to **gpt-5.4, reasoning=low** (not 5.5). **Local** model name = `contoso-reasoning-qwen25-7b`.
- **Test runner:** `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/...`. All unit tests mock keyring / urllib / subprocess — no network, no real installs.
- **Confirmed install/login commands (2026-07):** Claude — `winget install Anthropic.ClaudeCode` (fallback `irm https://claude.ai/install.ps1 | iex`), login `claude auth login`, creds file `%USERPROFILE%\.claude\.credentials.json`, `claude.exe` on PATH (no Node). Codex — Node.js 22+ (`winget install OpenJS.NodeJS.LTS`) then `npm install -g @openai/codex`, login `codex login`, detect `codex login status` (exit 0), Windows `.CMD` shim → `cmd /c`.

---

### Task 1: Register the Local provider + gateway URL setting (`config.py`, `settings.py`)

**Files:**
- Modify: `Dev/kb_chatbot/config.py` (add `local` to `PROVIDERS`, `MODEL_DISPLAY`, `COST_TABLE`)
- Modify: `Dev/kb_chatbot/settings.py` (add `reasoning_base_url` + `reasoning_username`)
- Test: `Dev/kb_chatbot/tests/test_config_local_provider.py`

**Interfaces:**
- Produces: `config.PROVIDERS["local"]` (display "Local (on-prem)", default_model `contoso-reasoning-qwen25-7b`); `config.LOCAL_MODEL` constant; `Settings.reasoning_base_url: str` (e.g. `http://<ip>:11500/v1`), `Settings.reasoning_username: str`. Loaded/saved by `load_settings`/`save_settings`.

- [ ] **Step 1: Write the failing test**

```python
# Dev/kb_chatbot/tests/test_config_local_provider.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config
from Dev.kb_chatbot import settings as S


def test_local_provider_registered():
    assert "local" in config.PROVIDERS
    assert config.PROVIDERS["local"]["default_model"] == "contoso-reasoning-qwen25-7b"
    assert config.default_model_for("local") == "contoso-reasoning-qwen25-7b"
    assert config.provider_of_model("contoso-reasoning-qwen25-7b") == "local"

def test_local_model_is_free_in_cost_table():
    assert config.COST_TABLE["contoso-reasoning-qwen25-7b"] == {"in": 0.0, "out": 0.0}

def test_settings_roundtrip_reasoning_fields(tmp_path):
    p = tmp_path / "settings.json"
    s = S.load_settings(p)
    s.reasoning_base_url = "http://192.0.2.50:11500/v1"
    s.reasoning_username = "abdul"
    S.save_settings(s, p)
    loaded = S.load_settings(p)
    assert loaded.reasoning_base_url == "http://192.0.2.50:11500/v1"
    assert loaded.reasoning_username == "abdul"
```

- [ ] **Step 2: Run to verify it fails**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_config_local_provider.py -v`
Expected: FAIL — `"local"` not in `PROVIDERS`.

- [ ] **Step 3: Add the provider to `config.py`**

In `PROVIDERS`, add after the `"openai"` entry:
```python
    "local": {
        "display": "Local (on-prem)",
        "default_model": "contoso-reasoning-qwen25-7b",
        "models": {
            "Contoso Reasoning (Qwen2.5-7B)": "contoso-reasoning-qwen25-7b",
        },
    },
```
Add a module constant near `EMBED_MODEL`:
```python
LOCAL_MODEL = "contoso-reasoning-qwen25-7b"
```
Add to `MODEL_DISPLAY`:
```python
    "contoso-reasoning-qwen25-7b": "Contoso Reasoning",
```
Add to `COST_TABLE`:
```python
    "contoso-reasoning-qwen25-7b": {"in": 0.0, "out": 0.0},   # on-prem, no per-token cost
```

- [ ] **Step 4: Add settings fields in `settings.py`**

In the `Settings` dataclass, add:
```python
    reasoning_base_url: str = ""
    reasoning_username: str = ""
```
In `load_settings`, add to the constructed `Settings(...)`:
```python
        reasoning_base_url=data.get("reasoning_base_url", ""),
        reasoning_username=data.get("reasoning_username", ""),
```
(`save_settings` uses `asdict`, so both persist automatically.)

- [ ] **Step 5: Run to verify it passes**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_config_local_provider.py -v`
Expected: PASS (3 passed). Also run `test_config_providers.py` + `test_settings.py` to confirm no regression.

- [ ] **Step 6: Commit**

```bash
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/settings.py Dev/kb_chatbot/tests/test_config_local_provider.py
git commit -m "feat(v3.0.1-p3): register Local (on-prem) provider + gateway URL/username settings"
```

---

### Task 2: Keyring credential store for the gateway (`llm/local_creds.py`)

**Files:**
- Create: `Dev/kb_chatbot/llm/local_creds.py`
- Modify: `Dev/kb_chatbot/requirements.txt` (add `keyring`)
- Test: `Dev/kb_chatbot/tests/test_local_creds.py`

**Interfaces:**
- Produces: `set_password(username, password)`, `get_password(username) -> Optional[str]`, `delete_password(username)`, constant `SERVICE = "contoso-kb-reasoning"`. Uses `keyring`; password never returned in logs.

- [ ] **Step 1: Write the failing test (fake keyring backend)**

```python
# Dev/kb_chatbot/tests/test_local_creds.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import keyring
from keyring.backend import KeyringBackend
from Dev.kb_chatbot.llm import local_creds


class _MemKeyring(KeyringBackend):
    priority = 1
    def __init__(self): self._d = {}
    def get_password(self, service, username): return self._d.get((service, username))
    def set_password(self, service, username, password): self._d[(service, username)] = password
    def delete_password(self, service, username): self._d.pop((service, username), None)


def _use_mem(monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: _MemKeyring())
    mem = _MemKeyring()
    monkeypatch.setattr(keyring, "get_password", mem.get_password)
    monkeypatch.setattr(keyring, "set_password", mem.set_password)
    monkeypatch.setattr(keyring, "delete_password", mem.delete_password)


def test_set_get_roundtrip(monkeypatch):
    _use_mem(monkeypatch)
    local_creds.set_password("abdul", "s3cret")
    assert local_creds.get_password("abdul") == "s3cret"

def test_get_missing_returns_none(monkeypatch):
    _use_mem(monkeypatch)
    assert local_creds.get_password("nobody") is None

def test_delete(monkeypatch):
    _use_mem(monkeypatch)
    local_creds.set_password("abdul", "x")
    local_creds.delete_password("abdul")
    assert local_creds.get_password("abdul") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_local_creds.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Add `keyring` to `requirements.txt`** (after `rank-bm25`):
```text
keyring>=24
```

- [ ] **Step 4: Implement `llm/local_creds.py`**

```python
"""Per-user gateway credentials in the OS keyring. The password is never written
to settings.json, logs, or anywhere on disk outside the keyring."""
from __future__ import annotations
from typing import Optional

import keyring

SERVICE = "contoso-kb-reasoning"


def set_password(username: str, password: str) -> None:
    keyring.set_password(SERVICE, username, password)


def get_password(username: str) -> Optional[str]:
    if not username:
        return None
    return keyring.get_password(SERVICE, username)


def delete_password(username: str) -> None:
    try:
        keyring.delete_password(SERVICE, username)
    except keyring.errors.PasswordDeleteError:
        pass
```

- [ ] **Step 5: Run to verify it passes**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_local_creds.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add Dev/kb_chatbot/llm/local_creds.py Dev/kb_chatbot/requirements.txt Dev/kb_chatbot/tests/test_local_creds.py
git commit -m "feat(v3.0.1-p3): keyring-backed per-user gateway credential store"
```

---

### Task 3: `LocalProvider` — OpenAI-compatible HTTP + Basic auth (`llm/local_provider.py`)

**Files:**
- Create: `Dev/kb_chatbot/llm/local_provider.py`
- Test: `Dev/kb_chatbot/tests/test_local_provider.py`

**Interfaces:**
- Consumes: `LLMProvider`/`LLMResponse`/`estimate_cost` (base), `local_creds` (T2), `config.LOCAL_MODEL`.
- Produces: `LocalProvider(base_url, username, password)` implementing `chat(...)` → `LLMResponse`; raises `LocalProviderError` on missing creds / HTTP error / bad JSON. `warm_up(...)` is a no-op. A module `_build_payload(messages, model, system_prompt, max_tokens) -> dict` (pure, unit-tested) and `_post_json(url, headers, payload) -> dict` (thin urllib wrapper, monkeypatched in tests).

- [ ] **Step 1: Write the failing test**

```python
# Dev/kb_chatbot/tests/test_local_provider.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest
from Dev.kb_chatbot.llm import local_provider as LP
from Dev.kb_chatbot.llm.local_provider import LocalProvider, LocalProviderError


def test_build_payload_prepends_system_and_flattens_multimodal():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": [
            {"type": "text", "text": "look at this"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "xxx"}},
        ]},
    ]
    p = LP._build_payload(msgs, "contoso-reasoning-qwen25-7b", "SYSTEM", 256)
    assert p["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert p["messages"][-1]["content"] == "look at this"     # image dropped, text kept
    assert p["temperature"] == 0 and p["seed"] == 42 and p["stream"] is False
    assert p["model"] == "contoso-reasoning-qwen25-7b"


def test_chat_returns_llmresponse(monkeypatch):
    def fake_post(url, headers, payload):
        assert url.endswith("/chat/completions")
        assert headers["Authorization"].startswith("Basic ")
        return {"choices": [{"message": {"content": "the answer"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5}}
    monkeypatch.setattr(LP, "_post_json", fake_post)
    prov = LocalProvider("http://x:11500/v1", "abdul", "pw")
    r = prov.chat(messages=[{"role": "user", "content": "q"}],
                  model="contoso-reasoning-qwen25-7b", system_prompt="SYS", max_tokens=128)
    assert r.text == "the answer"
    assert r.input_tokens == 12 and r.output_tokens == 5
    assert r.cost_estimate_usd == 0.0


def test_missing_password_raises():
    with pytest.raises(LocalProviderError):
        LocalProvider("http://x:11500/v1", "abdul", None)


def test_http_error_raises(monkeypatch):
    def boom(url, headers, payload):
        raise OSError("connection refused")
    monkeypatch.setattr(LP, "_post_json", boom)
    prov = LocalProvider("http://x:11500/v1", "abdul", "pw")
    with pytest.raises(LocalProviderError):
        prov.chat(messages=[{"role": "user", "content": "q"}],
                  model="contoso-reasoning-qwen25-7b", system_prompt="SYS")
```

- [ ] **Step 2: Run to verify it fails**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_local_provider.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `llm/local_provider.py`**

```python
"""LocalProvider: the on-prem fine-tuned model behind the AI-PC gateway.

OpenAI-compatible POST to <base_url>/chat/completions with HTTP Basic auth.
Deterministic (temperature 0 + fixed seed). Text-only: image blocks are dropped
(the local model is a text model). No provider API key — LAN Basic-auth only."""
from __future__ import annotations
import base64
import json
import logging
import time
import urllib.request
from typing import Optional

from Dev.kb_chatbot.llm.base import LLMProvider, LLMResponse, estimate_cost

log = logging.getLogger("kb_chatbot.llm.local")

_TIMEOUT_S = 180
_SEED = 42


class LocalProviderError(RuntimeError):
    """Local gateway unreachable / unauthorized / bad response / missing creds."""


def _flatten(content) -> str:
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    return str(content)


def _build_payload(messages: list[dict], model: str, system_prompt: str, max_tokens: int) -> dict:
    out = [{"role": "system", "content": system_prompt}]
    for m in messages:
        out.append({"role": m.get("role", "user"), "content": _flatten(m.get("content", ""))})
    return {"model": model, "messages": out, "temperature": 0, "seed": _SEED,
            "stream": False, "max_tokens": max_tokens}


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


class LocalProvider(LLMProvider):
    def __init__(self, base_url: str, username: str, password: Optional[str]) -> None:
        if not base_url or not username or not password:
            raise LocalProviderError(
                "Local model not configured. Set the gateway URL + username in Settings "
                "and enter the password (stored in the OS keyring).")
        self.base_url = base_url.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    def warm_up(self, system_prompt: str, model: str) -> None:
        pass  # first request wakes the model (Ollama loads on demand)

    def chat(self, *, messages, model, system_prompt, max_tokens: int = 1024) -> LLMResponse:
        started = time.time()
        url = f"{self.base_url}/chat/completions"
        payload = _build_payload(messages, model, system_prompt, max_tokens)
        try:
            body = _post_json(url, self._headers, payload)
        except Exception as exc:
            raise LocalProviderError(f"Local gateway request failed: {type(exc).__name__}") from exc
        try:
            text = (body["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LocalProviderError("Local gateway returned an unexpected response shape") from exc
        usage = body.get("usage") or {}
        tin = int(usage.get("prompt_tokens", 0) or 0)
        tout = int(usage.get("completion_tokens", 0) or 0)
        if not tin and not tout:
            tin = max(1, len(_flatten([{"content": system_prompt}])) // 4)
            tout = max(1, len(text) // 4)
        return LLMResponse(
            text=text, input_tokens=tin, output_tokens=tout, model=model,
            latency_ms=int((time.time() - started) * 1000),
            cost_estimate_usd=estimate_cost(model, tin, tout),
        )
```
**Security note:** the error messages deliberately name only the exception TYPE, never the URL/creds/response body (org policy: no secrets in logs).

- [ ] **Step 4: Run to verify it passes**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_local_provider.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/llm/local_provider.py Dev/kb_chatbot/tests/test_local_provider.py
git commit -m "feat(v3.0.1-p3): LocalProvider (OpenAI-compatible HTTP + Basic auth, deterministic)"
```

---

### Task 4: Provider factory (`llm/factory.py`)

**Files:**
- Create: `Dev/kb_chatbot/llm/factory.py`
- Test: `Dev/kb_chatbot/tests/test_provider_factory.py`

**Interfaces:**
- Consumes: `ClaudeCodeProvider`, `CodexProvider`, `FakeProvider`, `LocalProvider`, `local_creds`, `settings`.
- Produces: `make_provider(provider_id, settings=None) -> LLMProvider`. `local` reads `settings.reasoning_base_url` + `settings.reasoning_username` + keyring password. `claude`/`openai` construct as today. Unknown → `ValueError`.

- [ ] **Step 1: Write the failing test**

```python
# Dev/kb_chatbot/tests/test_provider_factory.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest
from Dev.kb_chatbot.llm import factory
from Dev.kb_chatbot.llm.local_provider import LocalProvider, LocalProviderError


class _S:
    reasoning_base_url = "http://x:11500/v1"
    reasoning_username = "abdul"


def test_make_local_provider(monkeypatch):
    monkeypatch.setattr(factory.local_creds, "get_password", lambda u: "pw")
    prov = factory.make_provider("local", settings=_S())
    assert isinstance(prov, LocalProvider)


def test_make_local_without_password_raises(monkeypatch):
    monkeypatch.setattr(factory.local_creds, "get_password", lambda u: None)
    with pytest.raises(LocalProviderError):
        factory.make_provider("local", settings=_S())


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        factory.make_provider("nope")
```

- [ ] **Step 2: Run to verify it fails**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_provider_factory.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `llm/factory.py`**

```python
"""Construct an LLMProvider from a provider id + settings."""
from __future__ import annotations
from typing import Optional

from Dev.kb_chatbot.llm.base import LLMProvider
from Dev.kb_chatbot.llm import local_creds


def make_provider(provider_id: str, settings: Optional[object] = None) -> LLMProvider:
    if provider_id == "claude":
        from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeProvider
        return ClaudeCodeProvider()
    if provider_id == "openai":
        from Dev.kb_chatbot.llm.codex_provider import CodexProvider
        return CodexProvider()
    if provider_id == "local":
        from Dev.kb_chatbot.llm.local_provider import LocalProvider
        base_url = getattr(settings, "reasoning_base_url", "") if settings else ""
        username = getattr(settings, "reasoning_username", "") if settings else ""
        password = local_creds.get_password(username)
        return LocalProvider(base_url, username, password)
    if provider_id == "fake":
        from Dev.kb_chatbot.llm.fake_provider import FakeProvider
        return FakeProvider(canned_text="stub")
    raise ValueError(f"unknown provider: {provider_id}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_provider_factory.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/llm/factory.py Dev/kb_chatbot/tests/test_provider_factory.py
git commit -m "feat(v3.0.1-p3): provider factory (claude/openai/local/fake)"
```

---

### Task 5: Onboarding — detect + install/login command construction (`onboarding/`)

**Files:**
- Create: `Dev/kb_chatbot/onboarding/__init__.py`
- Create: `Dev/kb_chatbot/onboarding/providers.py`
- Test: `Dev/kb_chatbot/tests/test_onboarding.py`

**Interfaces:**
- Produces: `Readiness` dataclass (`provider_id`, `installed: bool`, `logged_in: bool`, `ready: bool`, `needs: list[str]`); `check(provider_id, settings=None) -> Readiness`; `install_commands(provider_id) -> list[list[str]]` (exact argv lists, pure); `login_command(provider_id) -> Optional[list[str]]`; `run_visible(argv) -> None` (spawns a visible console — thin, monkeypatched in tests). Detection uses `shutil.which` + the Claude creds file + `codex login status`.

- [ ] **Step 1: Write the failing test**

```python
# Dev/kb_chatbot/tests/test_onboarding.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.onboarding import providers as OB


def test_claude_install_commands_use_winget_no_node():
    cmds = OB.install_commands("claude")
    flat = " ".join(" ".join(c) for c in cmds).lower()
    assert "anthropic.claudecode" in flat
    assert "npm" not in flat and "nodejs" not in flat

def test_codex_install_requires_node_and_npm_package():
    cmds = OB.install_commands("codex")
    flat = " ".join(" ".join(c) for c in cmds).lower()
    assert "openjs.nodejs" in flat
    assert "@openai/codex" in flat

def test_local_needs_no_install():
    assert OB.install_commands("local") == []

def test_login_commands():
    assert OB.login_command("claude") == ["claude", "auth", "login"]
    assert OB.login_command("codex") == ["codex", "login"]
    assert OB.login_command("local") is None

def test_check_claude_not_installed(monkeypatch):
    monkeypatch.setattr(OB.shutil, "which", lambda x: None)
    r = OB.check("claude")
    assert r.installed is False and r.ready is False and "install" in r.needs

def test_check_local_ready_when_creds_present(monkeypatch):
    class S: reasoning_base_url = "http://x:11500/v1"; reasoning_username = "abdul"
    monkeypatch.setattr(OB.local_creds, "get_password", lambda u: "pw")
    r = OB.check("local", settings=S())
    assert r.ready is True

def test_check_local_not_ready_without_password(monkeypatch):
    class S: reasoning_base_url = "http://x:11500/v1"; reasoning_username = "abdul"
    monkeypatch.setattr(OB.local_creds, "get_password", lambda u: None)
    r = OB.check("local", settings=S())
    assert r.ready is False and "credentials" in r.needs
```

- [ ] **Step 2: Run to verify it fails**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_onboarding.py -v`
Expected: FAIL — package missing.

- [ ] **Step 3: Write `onboarding/__init__.py`**

```python
# Dev/kb_chatbot/onboarding/__init__.py
"""First-run provider onboarding: detect, install, login."""
```

- [ ] **Step 4: Implement `onboarding/providers.py`**

```python
"""Detect each reasoning provider's readiness and return the exact install/login
commands. Actions run in a VISIBLE console (the app hides normal subprocesses).

Confirmed 2026-07:
  Claude - native install (winget / PowerShell), no Node; login `claude auth login`;
           creds at %USERPROFILE%\\.claude\\.credentials.json; `claude.exe` on PATH.
  Codex  - Node.js 22+ then `npm install -g @openai/codex`; login `codex login`;
           detect via `codex login status` (exit 0); Windows `.CMD` shim.
  Local  - no install; needs gateway URL + username (settings) + password (keyring)."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from Dev.kb_chatbot.llm import local_creds


@dataclass
class Readiness:
    provider_id: str
    installed: bool = False
    logged_in: bool = False
    ready: bool = False
    needs: list[str] = field(default_factory=list)


def install_commands(provider_id: str) -> list[list[str]]:
    if provider_id == "claude":
        return [["winget", "install", "--id", "Anthropic.ClaudeCode", "-e",
                 "--accept-source-agreements", "--accept-package-agreements"]]
    if provider_id == "codex":
        return [["winget", "install", "--id", "OpenJS.NodeJS.LTS", "-e",
                 "--accept-source-agreements", "--accept-package-agreements"],
                ["npm", "install", "-g", "@openai/codex"]]
    return []


def login_command(provider_id: str) -> Optional[list[str]]:
    if provider_id == "claude":
        return ["claude", "auth", "login"]
    if provider_id == "codex":
        return ["codex", "login"]
    return None


def _claude_logged_in() -> bool:
    creds = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".claude" / ".credentials.json"
    if creds.exists() and creds.stat().st_size > 0:
        return True
    exe = shutil.which("claude")
    if not exe:
        return False
    try:
        return subprocess.run([exe, "auth", "status"], capture_output=True,
                              timeout=10).returncode == 0
    except Exception:
        return False


def _codex_logged_in() -> bool:
    exe = shutil.which("codex")
    if not exe:
        return False
    argv = ["cmd", "/c", exe, "login", "status"] if sys.platform == "win32" \
        and exe.lower().endswith((".cmd", ".bat")) else [exe, "login", "status"]
    try:
        return subprocess.run(argv, capture_output=True, timeout=10).returncode == 0
    except Exception:
        return False


def check(provider_id: str, settings: Optional[object] = None) -> Readiness:
    r = Readiness(provider_id=provider_id)
    if provider_id == "local":
        url = getattr(settings, "reasoning_base_url", "") if settings else ""
        user = getattr(settings, "reasoning_username", "") if settings else ""
        has_pw = bool(local_creds.get_password(user)) if user else False
        r.installed = True  # nothing to install
        r.logged_in = bool(url and user and has_pw)
        r.ready = r.logged_in
        if not (url and user):
            r.needs.append("gateway-url-and-username")
        if not has_pw:
            r.needs.append("credentials")
        return r
    exe = "claude" if provider_id == "claude" else "codex"
    r.installed = shutil.which(exe) is not None
    if not r.installed:
        r.needs.append("install")
    r.logged_in = _claude_logged_in() if provider_id == "claude" else _codex_logged_in()
    if r.installed and not r.logged_in:
        r.needs.append("login")
    r.ready = r.installed and r.logged_in
    return r


def run_visible(argv: list[str]) -> None:
    """Launch a command in a NEW VISIBLE console (the app hides normal subprocesses,
    but install/login need to be user-visible + interactive)."""
    if sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", "start", "", *argv], close_fds=True)
    else:
        subprocess.Popen(argv)
```

- [ ] **Step 5: Run to verify it passes**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/test_onboarding.py -v`
Expected: PASS (7 passed).

- [ ] **Step 6: Commit**

```bash
git add Dev/kb_chatbot/onboarding Dev/kb_chatbot/tests/test_onboarding.py
git commit -m "feat(v3.0.1-p3): onboarding detect + install/login commands (claude/codex/local)"
```

---

### Task 6: Live-smoke script + full-suite regression

**Files:**
- Create: `Dev/kb_chatbot/eval/local_smoke.py` (operator-run against the live gateway)

**Interfaces:**
- Consumes: `LocalProvider`, `local_creds`, `settings`.

- [ ] **Step 1: Write the live-smoke script**

```python
"""Live smoke for the Local provider against the AI-PC gateway (operator-run).

Reads gateway URL + username from settings.json and the password from the keyring
(or --password). Never prints the password.

  python -m Dev.kb_chatbot.eval.local_smoke --base-url http://<ip>:11500/v1 --username abdul --password <pw>
"""
from __future__ import annotations
import argparse

from Dev.kb_chatbot.llm.local_provider import LocalProvider
from Dev.kb_chatbot.llm import local_creds
from Dev.kb_chatbot import settings as S


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="")
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    args = ap.parse_args()

    st = S.load_settings()
    base_url = args.base_url or st.reasoning_base_url
    username = args.username or st.reasoning_username
    password = args.password or local_creds.get_password(username)
    if not (base_url and username and password):
        raise SystemExit("Need base_url + username + password (settings/keyring or flags).")

    prov = LocalProvider(base_url, username, password)
    r = prov.chat(messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                  model="contoso-reasoning-qwen25-7b",
                  system_prompt="You are a test harness. Answer tersely.", max_tokens=32)
    print(f"OK response: {r.text!r}  ({r.input_tokens} in / {r.output_tokens} out, {r.latency_ms} ms)")
    # Determinism check: same question twice -> identical text (temp 0 + seed).
    r2 = prov.chat(messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                   model="contoso-reasoning-qwen25-7b",
                   system_prompt="You are a test harness. Answer tersely.", max_tokens=32)
    print("DETERMINISTIC" if r.text == r2.text else "WARN: non-deterministic output")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Full suite**

Run: `scraper\venv\Scripts\python.exe -m pytest Dev/kb_chatbot/tests/ -q`
Expected: all pass (Phase-3 tests + prior). No network hit (all mocked).

- [ ] **Step 3: Commit**

```bash
git add Dev/kb_chatbot/eval/local_smoke.py
git commit -m "feat(v3.0.1-p3): live-smoke for the Local provider (operator-run)"
```

- [ ] **Step 4: Operator live check (needs the AI-PC gateway + your per-user creds)**

Run on your machine (creds from the AI-PC provisioning; not committed):
`scraper\venv\Scripts\python.exe -m Dev.kb_chatbot.eval.local_smoke --base-url http://<SERVER_LAN_IP>:11500/v1 --username <you> --password <pw>`
Expected: `OK response: 'OK'` + `DETERMINISTIC`.

---

## Deferred to Phase 6 (UI)
- The top-bar provider/model **selector**, per-provider **readiness dots**, the first-run **onboarding wizard** (calls `onboarding.check` → shows what's missing → `run_visible(install/login)`), and the Settings fields for gateway URL/username + a password box that writes to `local_creds`. This phase delivers the headless backend + factory + onboarding logic those will call.
- The orchestrator/gui swap from directly constructing a provider to `factory.make_provider(settings.default_provider, settings)`.

## Self-Review (completed)
- **Spec coverage (spec §6.3):** 3 selectable providers ✓ (config + factory), Local HTTP+Basic-auth deterministic ✓ (T3), per-user keyring creds ✓ (T2), onboarding detect/install/login with confirmed commands ✓ (T5), Codex pinned gpt-5.4 (unchanged) ✓, no API keys ✓. Fully-automatic install uses `run_visible` for the interactive OAuth ✓. UI wiring explicitly deferred to Phase 6 ✓.
- **Placeholder scan:** none — full code for every module + tests; `<SERVER_LAN_IP>`/`<pw>` are operator runtime values.
- **Type/name consistency:** `LocalProvider`/`LocalProviderError`/`_build_payload`/`_post_json` (T3) used by the factory (T4) + smoke (T6); `local_creds.get_password` (T2) used by T4/T5/T6; `config.LOCAL_MODEL` + `PROVIDERS["local"]` (T1) referenced throughout; `Readiness`/`check`/`install_commands`/`login_command`/`run_visible` (T5) names match their tests.
- **Security:** password only in keyring; error strings name exception TYPE only; no creds/URL in logs; images dropped (text-only local model).
