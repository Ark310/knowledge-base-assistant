# KB Chatbot v2.5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenAI/ChatGPT as a second selectable AI provider (via the Codex CLI subprocess, account-based, no API key) with an AI Provider dropdown, per-provider models, provider-aware cost accounting, and in-window provider/model-change notices.

**Architecture:** A new `CodexProvider(LLMProvider)` mirrors `ClaudeCodeProvider` but shells out to `codex exec` (stateless per call, flattens the full message list). A provider registry in `config.py` drives the GUI dropdowns and the cost table. The retrieval rewrite-escalation becomes provider-aware. The orchestrator and retrieval core are untouched.

**Tech Stack:** PySide6, Codex CLI (`codex exec`, v0.130.0), claude-agent-sdk (unchanged), Python 3.12.

**Working directory:** repo root. **Branch:** `feature/kb-chatbot-v2.5`. **Test command:** `& "scraper\venv\Scripts\python.exe" -m pytest <path> -v`

---

## File Map

| File | Status | Responsibility |
|------|--------|----------------|
| `Dev/kb_chatbot/config.py` | Modify | `PROVIDERS` registry, derived aliases, OpenAI `COST_TABLE` rows, `MODEL_DISPLAY`, helper fns |
| `Dev/kb_chatbot/llm/codex_provider.py` | **New** | `CodexProvider`, `CodexNotFoundError`, `codex_login_ok`, `_run_codex_exec`, flatten/parse helpers |
| `Dev/kb_chatbot/chat/query_rewriter.py` | Modify | `RewriteResult.model`, `make_rewriter`, `rewrite_query_codex` |
| `Dev/kb_chatbot/chat/orchestrator.py` | Modify | Log rewrite Turn with `model=rw.model or _REWRITE_MODEL_NAME` |
| `Dev/kb_chatbot/settings.py` | Modify | `default_provider` field + load + validation guard |
| `Dev/kb_chatbot/gui.py` | Modify | Provider dropdown, repopulation, notices, `build_provider`, `_send`, InitWorker, preflight, SettingsDialog pair, TokenUsageDialog display/footer |
| `Dev/kb_chatbot/tests/test_config_providers.py` | **New** | Registry integrity + helpers |
| `Dev/kb_chatbot/tests/test_codex_provider.py` | **New** | Flatten/parse/usage/images + chat (subprocess stubbed) |
| `Dev/kb_chatbot/tests/test_query_rewriter.py` | Extend | `make_rewriter`, `RewriteResult.model` |
| `Dev/kb_chatbot/tests/test_settings.py` | Extend | `default_provider` round-trip + validation guard |

---

## Task 1: Provider Registry + Cost Table (`config.py`)

**Files:**
- Modify: `Dev/kb_chatbot/config.py`
- Test: `Dev/kb_chatbot/tests/test_config_providers.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `Dev/kb_chatbot/tests/test_config_providers.py`:

```python
from Dev.kb_chatbot import config


def test_providers_have_claude_and_openai():
    assert set(config.PROVIDERS) == {"claude", "openai"}


def test_default_provider_is_claude():
    assert config.DEFAULT_PROVIDER == "claude"


def test_backward_compat_aliases():
    assert config.DEFAULT_MODEL == config.PROVIDERS["claude"]["default_model"]
    assert config.AVAILABLE_MODELS == config.PROVIDERS["claude"]["models"]


def test_every_model_has_cost_and_display():
    for prov in config.PROVIDERS.values():
        for model_id in prov["models"].values():
            assert model_id in config.COST_TABLE, f"{model_id} missing from COST_TABLE"
            assert model_id in config.MODEL_DISPLAY, f"{model_id} missing from MODEL_DISPLAY"


def test_openai_models_present():
    ids = set(config.PROVIDERS["openai"]["models"].values())
    assert ids == {"gpt-5.5", "gpt-5.4", "gpt-5.4-mini"}


def test_openai_costs():
    assert config.COST_TABLE["gpt-5.5"] == {"in": 5.00, "out": 30.00}
    assert config.COST_TABLE["gpt-5.4"] == {"in": 2.50, "out": 15.00}
    assert config.COST_TABLE["gpt-5.4-mini"] == {"in": 0.75, "out": 4.50}


def test_models_for():
    assert config.models_for("openai") == config.PROVIDERS["openai"]["models"]
    # Unknown provider falls back to the default provider's models
    assert config.models_for("nope") == config.PROVIDERS["claude"]["models"]


def test_default_model_for():
    assert config.default_model_for("openai") == "gpt-5.5"
    assert config.default_model_for("claude") == "claude-sonnet-4-6"


def test_provider_of_model():
    assert config.provider_of_model("gpt-5.4-mini") == "openai"
    assert config.provider_of_model("claude-sonnet-4-6") == "claude"
    assert config.provider_of_model("mystery") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_config_providers.py -v`
Expected: AttributeError — `config.PROVIDERS` not defined.

- [ ] **Step 3: Implement in `config.py`**

Add `from typing import Optional` to the imports at the top (alongside `import sys`).

Replace the existing model-defaults block:
```python
DEFAULT_MODEL  = "claude-sonnet-4-6"
AVAILABLE_MODELS = {
    "Haiku (fast / cheap)": "claude-haiku-4-5-20251001",
    "Sonnet (smarter)":     "claude-sonnet-4-6",
}
```
with:
```python
DEFAULT_PROVIDER = "claude"

PROVIDERS = {
    "claude": {
        "display": "Claude",
        "default_model": "claude-sonnet-4-6",
        "models": {
            "Haiku (fast / cheap)": "claude-haiku-4-5-20251001",
            "Sonnet (smarter)":     "claude-sonnet-4-6",
        },
    },
    "openai": {
        "display": "ChatGPT",
        "default_model": "gpt-5.5",
        "models": {
            "GPT-5.5 (smartest)":  "gpt-5.5",
            "GPT-5.4 (mid)":       "gpt-5.4",
            "GPT-5.4-mini (fast)": "gpt-5.4-mini",
        },
    },
}

# Backward-compatible aliases (Claude provider) so existing imports keep working
DEFAULT_MODEL    = PROVIDERS["claude"]["default_model"]
AVAILABLE_MODELS = PROVIDERS["claude"]["models"]

MODEL_DISPLAY = {
    "claude-haiku-4-5-20251001": "Haiku",
    "claude-sonnet-4-6":         "Sonnet",
    "gpt-5.5":                   "GPT-5.5",
    "gpt-5.4":                   "GPT-5.4",
    "gpt-5.4-mini":              "GPT-5.4-mini",
}


def models_for(provider_id: str) -> dict:
    return PROVIDERS.get(provider_id, PROVIDERS[DEFAULT_PROVIDER])["models"]


def default_model_for(provider_id: str) -> str:
    return PROVIDERS.get(provider_id, PROVIDERS[DEFAULT_PROVIDER])["default_model"]


def provider_of_model(model_id: str) -> Optional[str]:
    for pid, prov in PROVIDERS.items():
        if model_id in prov["models"].values():
            return pid
    return None
```

In the `COST_TABLE` dict, add the OpenAI rows (keep the Claude rows):
```python
COST_TABLE: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
    "claude-sonnet-4-6":         {"in": 3.00, "out": 15.00},
    "gpt-5.5":                   {"in": 5.00, "out": 30.00},
    "gpt-5.4":                   {"in": 2.50, "out": 15.00},
    "gpt-5.4-mini":              {"in": 0.75, "out": 4.50},
}
```

- [ ] **Step 4: Run to verify pass**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_config_providers.py -v`
Expected: 9 PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/tests/test_config_providers.py
git commit -m "feat(v2.5): provider registry, OpenAI cost rows, model display map, helpers"
```

---

## Task 2: CodexProvider

**Files:**
- Create: `Dev/kb_chatbot/llm/codex_provider.py`
- Test: `Dev/kb_chatbot/tests/test_codex_provider.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `Dev/kb_chatbot/tests/test_codex_provider.py`:

```python
import base64
import json
from Dev.kb_chatbot.llm import codex_provider as cp


def test_flatten_messages_includes_system_history_and_latest():
    msgs = [
        {"role": "user", "content": "How do I post a deal?"},
        {"role": "assistant", "content": "Which product?"},
        {"role": "user", "content": "CONTEXT…\nUSER QUESTION:\nTradeDesk"},
    ]
    out = cp._flatten_messages("SYSTEM RULES HERE", msgs)
    assert "SYSTEM RULES HERE" in out
    assert "How do I post a deal?" in out
    assert "Which product?" in out
    assert "TradeDesk" in out
    assert "USER:" in out and "ASSISTANT:" in out


def test_flatten_messages_extracts_text_from_multimodal():
    msgs = [{"role": "user", "content": [
        {"type": "image", "source": {}},
        {"type": "text", "text": "what is this error"},
    ]}]
    out = cp._flatten_messages("SYS", msgs)
    assert "what is this error" in out


def test_parse_usage_reads_turn_completed():
    stdout = "\n".join([
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 65608, "cached_input_tokens": 2432,
            "output_tokens": 19, "reasoning_output_tokens": 12}}),
    ])
    tin, tout = cp._parse_usage(stdout)
    assert tin == 65608
    assert tout == 31  # output_tokens + reasoning_output_tokens


def test_parse_usage_skips_non_json_lines():
    stdout = "ERROR some stderr-like noise\n" + json.dumps(
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}})
    tin, tout = cp._parse_usage(stdout)
    assert tin == 10 and tout == 5


def test_parse_usage_none_found():
    assert cp._parse_usage("not json at all\n{\"type\":\"turn.started\"}") == (0, 0)


def test_extract_agent_message():
    stdout = "\n".join([
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "pong"}}),
    ])
    assert cp._extract_agent_message(stdout) == "pong"


def test_extract_image_files_writes_and_returns_paths(tmp_path, monkeypatch):
    import tempfile
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    raw = b"\x89PNG\r\n"
    b64 = base64.b64encode(raw).decode()
    msgs = [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
        {"type": "text", "text": "q"},
    ]}]
    paths = cp._extract_image_files(msgs)
    assert len(paths) == 1
    with open(paths[0], "rb") as fh:
        assert fh.read() == raw
    import os
    for p in paths:
        os.unlink(p)


def test_chat_stubbed_subprocess(monkeypatch):
    # Stub the subprocess so no real codex runs.
    class _Proc:
        stdout = json.dumps({"type": "turn.completed",
                             "usage": {"input_tokens": 100, "output_tokens": 20,
                                       "reasoning_output_tokens": 5}})
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kwargs):
        # codex exec -o <path> … : write the answer to the -o file
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("Here is the answer.")
        return _Proc()

    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run", fake_run)

    provider = cp.CodexProvider()
    resp = provider.chat(messages=[{"role": "user", "content": "hi"}],
                         model="gpt-5.4-mini", system_prompt="SYS")
    assert resp.text == "Here is the answer."
    assert resp.input_tokens == 100
    assert resp.output_tokens == 25  # 20 + 5
    assert resp.model == "gpt-5.4-mini"
    assert resp.cost_estimate_usd > 0


def test_ensure_codex_available_raises_when_missing(monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    try:
        cp._ensure_codex_available()
        assert False, "expected CodexNotFoundError"
    except cp.CodexNotFoundError:
        pass


def test_codex_login_ok_false_when_missing(monkeypatch):
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    assert cp.codex_login_ok() is False
```

- [ ] **Step 2: Run to verify failure**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_codex_provider.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Create `Dev/kb_chatbot/llm/codex_provider.py`**

```python
"""CodexProvider: OpenAI/ChatGPT via the Codex CLI subprocess (account-based).

Mirrors ClaudeCodeProvider but shells out to `codex exec` once per turn. codex
exec is stateless, so the full message list is flattened into one prompt. No API
key: auth rides the user's ChatGPT account via `codex login`. The sandbox is
locked to read-only so Codex cannot modify files or run commands."""
from __future__ import annotations
import base64
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from typing import Optional

# Import for the Windows hidden-subprocess patch side-effect (patches Popen).
from Dev.kb_chatbot.llm import claude_code_provider as _provider  # noqa: F401
from Dev.kb_chatbot.llm.base import LLMProvider, LLMResponse, estimate_cost

log = logging.getLogger("kb_chatbot.llm.codex")

CODEX_TIMEOUT_S = 180

_IMG_EXT = {"image/png": ".png", "image/jpeg": ".jpg",
            "image/gif": ".gif", "image/webp": ".webp"}


class CodexNotFoundError(RuntimeError):
    """Raised when the `codex` CLI cannot be located on PATH."""


def _ensure_codex_available() -> str:
    path = shutil.which("codex")
    if not path:
        raise CodexNotFoundError(
            "Codex CLI not found on PATH. Install it and run `codex login` once, "
            "then re-launch this app."
        )
    return path


def codex_login_ok() -> bool:
    """True if `codex login status` reports an authenticated account."""
    if not shutil.which("codex"):
        return False
    try:
        r = subprocess.run(["codex", "login", "status"],
                           capture_output=True, text=True, timeout=20)
    except Exception:
        return False
    return r.returncode == 0


def _flatten_messages(system_prompt: str, messages: list[dict]) -> str:
    """Flatten system prompt + full conversation into one prompt string.
    codex exec is stateless and has no separate system channel, so the system
    prompt leads. Multimodal image blocks are dropped here (passed via -i)."""
    parts = [system_prompt.strip(), ""]
    for m in messages:
        role = m.get("role", "user").upper()
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(b.get("text", "") for b in content
                               if b.get("type") == "text")
        parts.append(f"{role}: {content}")
    return "\n".join(parts).strip()


def _extract_image_files(messages: list[dict]) -> list[str]:
    """Decode base64 image blocks from the latest user message to temp files.
    Returns temp paths (caller deletes them)."""
    paths: list[str] = []
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if b.get("type") == "image":
                    src = b.get("source", {}) or {}
                    if src.get("type") == "base64":
                        ext = _IMG_EXT.get(src.get("media_type", ""), ".png")
                        fd, p = tempfile.mkstemp(suffix=ext, prefix="kbimg_")
                        try:
                            with os.fdopen(fd, "wb") as fh:
                                fh.write(base64.b64decode(src.get("data", "")))
                            paths.append(p)
                        except Exception:
                            log.exception("Failed to write image temp file")
                            try:
                                os.unlink(p)
                            except OSError:
                                pass
        break  # only the latest user message carries fresh attachments
    return paths


def _parse_usage(stdout: str) -> tuple[int, int]:
    """(input_tokens, output_tokens) from codex --json stdout. output =
    output_tokens + reasoning_output_tokens (reasoning is billable output)."""
    tin = tout = 0
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "turn.completed":
            u = ev.get("usage", {}) or {}
            tin = int(u.get("input_tokens", 0) or 0)
            tout = int((u.get("output_tokens", 0) or 0)
                       + (u.get("reasoning_output_tokens", 0) or 0))
    return tin, tout


def _extract_agent_message(stdout: str) -> str:
    """Fallback answer text: last agent_message item from --json stdout."""
    text = ""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "item.completed":
            item = ev.get("item", {}) or {}
            if item.get("type") == "agent_message":
                text = item.get("text", "") or text
    return text


def _run_codex_exec(prompt: str, model: str,
                    image_paths: Optional[list[str]] = None) -> tuple[str, int, int]:
    """Run one `codex exec` and return (text, input_tokens, output_tokens).
    Stateless, read-only sandbox, no repo. Shared by the chat and rewrite paths."""
    _ensure_codex_available()
    out_fd, out_path = tempfile.mkstemp(suffix=".txt", prefix="kbcodex_")
    os.close(out_fd)
    cmd = ["codex", "exec", "-m", model, "--json",
           "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
           "-o", out_path]
    for p in (image_paths or []):
        cmd += ["-i", p]
    cmd.append("-")  # read prompt from stdin
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True,
                              text=True, timeout=CODEX_TIMEOUT_S)
        try:
            with open(out_path, "r", encoding="utf-8") as fh:
                text = fh.read().strip()
        except Exception:
            text = ""
        if not text:
            text = _extract_agent_message(proc.stdout).strip()
        tin, tout = _parse_usage(proc.stdout)
        if not tin and not tout:
            tin = max(1, len(prompt) // 4)
            tout = max(1, len(text) // 4)
        return text, tin, tout
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


class CodexProvider(LLMProvider):
    """OpenAI/ChatGPT provider over `codex exec` (stateless subprocess per turn)."""

    def __init__(self) -> None:
        _ensure_codex_available()

    def warm_up(self, system_prompt: str, model: str) -> None:
        # codex exec is cold-start per call; nothing persistent to boot.
        pass

    def chat(self, *, messages, model, system_prompt, max_tokens: int = 1024) -> LLMResponse:
        started = time.time()
        prompt = _flatten_messages(system_prompt, messages)
        image_paths = _extract_image_files(messages)
        try:
            text, tin, tout = _run_codex_exec(prompt, model, image_paths)
        finally:
            for p in image_paths:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        return LLMResponse(
            text=text, input_tokens=tin, output_tokens=tout, model=model,
            latency_ms=int((time.time() - started) * 1000),
            cost_estimate_usd=estimate_cost(model, tin, tout),
        )
```

- [ ] **Step 4: Run to verify pass**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_codex_provider.py -v`
Expected: 10 PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/llm/codex_provider.py Dev/kb_chatbot/tests/test_codex_provider.py
git commit -m "feat(v2.5): CodexProvider — ChatGPT via codex exec subprocess"
```

---

## Task 3: Provider-Aware Rewriter

**Files:**
- Modify: `Dev/kb_chatbot/chat/query_rewriter.py`, `Dev/kb_chatbot/chat/orchestrator.py`
- Test: `Dev/kb_chatbot/tests/test_query_rewriter.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `Dev/kb_chatbot/tests/test_query_rewriter.py`:

```python
def test_rewrite_result_has_model_field_default_empty():
    from Dev.kb_chatbot.chat.query_rewriter import RewriteResult
    r = RewriteResult(query="q", tokens_in=1, tokens_out=1, latency_ms=1)
    assert r.model == ""


def test_make_rewriter_claude():
    from Dev.kb_chatbot.chat.query_rewriter import make_rewriter, rewrite_query
    assert make_rewriter("claude") is rewrite_query


def test_make_rewriter_openai():
    from Dev.kb_chatbot.chat.query_rewriter import make_rewriter, rewrite_query_codex
    assert make_rewriter("openai") is rewrite_query_codex


def test_make_rewriter_unknown_defaults_to_claude():
    from Dev.kb_chatbot.chat.query_rewriter import make_rewriter, rewrite_query
    assert make_rewriter("nope") is rewrite_query


def test_rewrite_query_codex_returns_result(monkeypatch):
    from Dev.kb_chatbot.chat import query_rewriter as qr
    monkeypatch.setattr(qr, "_run_codex_exec_for_rewrite",
                        lambda prompt, model: ("reverse posted deal tradedesk", 120, 8))
    out = qr.rewrite_query_codex("undo it", [{"role": "user", "content": "post a deal"}])
    assert out is not None
    assert out.query == "reverse posted deal tradedesk"
    assert out.model == "gpt-5.4-mini"
    assert out.tokens_in == 120 and out.tokens_out == 8


def test_rewrite_query_codex_none_on_failure(monkeypatch):
    from Dev.kb_chatbot.chat import query_rewriter as qr
    def boom(prompt, model):
        raise RuntimeError("codex down")
    monkeypatch.setattr(qr, "_run_codex_exec_for_rewrite", boom)
    assert qr.rewrite_query_codex("undo it", [{"role": "user", "content": "x"}]) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_query_rewriter.py -v`
Expected: failures — `RewriteResult.model`, `make_rewriter`, `rewrite_query_codex` not defined.

- [ ] **Step 3: Implement in `query_rewriter.py`**

Add `model: str = ""` to the `RewriteResult` dataclass:
```python
@dataclass
class RewriteResult:
    query: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    model: str = ""
```

In `rewrite_query` (the Claude path), set the model on the returned result:
```python
    return RewriteResult(query=query, tokens_in=tin, tokens_out=tout,
                         latency_ms=int((time.time() - started) * 1000),
                         model=REWRITE_MODEL)
```

Add the OpenAI rewrite constant and functions at the end of the file:
```python
REWRITE_MODEL_OPENAI = "gpt-5.4-mini"


def _run_codex_exec_for_rewrite(prompt: str, model: str) -> tuple[str, int, int]:
    """Thin indirection over CodexProvider._run_codex_exec so tests can stub it
    without importing the codex module."""
    from Dev.kb_chatbot.llm.codex_provider import _run_codex_exec
    return _run_codex_exec(prompt, model)


def rewrite_query_codex(user_msg: str, history: list[dict]) -> Optional[RewriteResult]:
    """OpenAI rewrite path: one stateless `codex exec` with gpt-5.4-mini. codex
    has no separate system channel, so the rewrite system prompt is prepended.
    Returns None on any failure (escalation is best-effort)."""
    started = time.time()
    prompt = REWRITE_SYSTEM_PROMPT + "\n\n" + build_rewrite_prompt(user_msg, history)
    try:
        text, tin, tout = _run_codex_exec_for_rewrite(prompt, REWRITE_MODEL_OPENAI)
    except Exception:
        log.exception("Codex query rewrite failed (non-fatal)")
        return None
    query = _clean_response(text)
    if not query:
        return None
    return RewriteResult(query=query, tokens_in=tin, tokens_out=tout,
                         latency_ms=int((time.time() - started) * 1000),
                         model=REWRITE_MODEL_OPENAI)


def make_rewriter(provider_id: str):
    """Return the rewrite callable for the active provider."""
    if provider_id == "openai":
        return rewrite_query_codex
    return rewrite_query
```

- [ ] **Step 4: Update the orchestrator rewrite-log to use the result's model**

In `Dev/kb_chatbot/chat/orchestrator.py`, the escalation block logs a `kind="rewrite"` Turn. Change its `model=` to prefer the rewriter's reported model:
```python
            deps.usage_logger(Turn(
                role="system", kind="rewrite", content=rw.query,
                model=getattr(rw, "model", "") or _REWRITE_MODEL_NAME,
                tokens_in=rw.tokens_in, tokens_out=rw.tokens_out,
                latency_ms=rw.latency_ms,
            ))
```

- [ ] **Step 5: Run tests**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_query_rewriter.py Dev/kb_chatbot/tests/test_orchestrator.py -v`
Expected: all PASS (existing rewriter tests still green — `model` has a default).

- [ ] **Step 6: Commit**

```
git add Dev/kb_chatbot/chat/query_rewriter.py Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_query_rewriter.py
git commit -m "feat(v2.5): provider-aware rewrite escalation (Claude Haiku / Codex gpt-5.4-mini)"
```

---

## Task 4: Settings — `default_provider` + Validation

**Files:**
- Modify: `Dev/kb_chatbot/settings.py`
- Test: `Dev/kb_chatbot/tests/test_settings.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `Dev/kb_chatbot/tests/test_settings.py`:

```python
def test_settings_has_default_provider_field():
    from Dev.kb_chatbot.settings import Settings
    assert "default_provider" in Settings.__dataclass_fields__


def test_default_provider_defaults_to_claude_when_absent():
    import tempfile
    from pathlib import Path
    from Dev.kb_chatbot.settings import load_settings
    with tempfile.TemporaryDirectory() as d:
        loaded = load_settings(Path(d) / "missing.json")
        assert loaded.default_provider == "claude"


def test_default_provider_round_trips():
    import tempfile, json
    from pathlib import Path
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import Settings, save_settings, load_settings
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "settings.json"
        s = Settings(library_path=config.LIBRARY_DEFAULT, default_model="gpt-5.5",
                     confidence_floor=config.CONFIDENCE_FLOOR,
                     default_provider="openai", model_explicitly_set=True)
        save_settings(s, p)
        loaded = load_settings(p)
        assert loaded.default_provider == "openai"
        assert loaded.default_model == "gpt-5.5"


def test_validation_resets_mismatched_model(tmp_path):
    import json
    from pathlib import Path
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import load_settings
    # openai provider but a Claude model — corrupt pairing
    p = Path(tmp_path) / "settings.json"
    p.write_text(json.dumps({
        "library_path": str(config.LIBRARY_DEFAULT),
        "default_provider": "openai",
        "default_model": "claude-sonnet-4-6",
        "confidence_floor": config.CONFIDENCE_FLOOR,
        "model_explicitly_set": True,
    }), encoding="utf-8")
    loaded = load_settings(p)
    assert loaded.default_provider == "openai"
    assert loaded.default_model == "gpt-5.5"  # reset to openai's default
```

- [ ] **Step 2: Run to verify failure**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_settings.py -v`
Expected: failures on the new tests.

- [ ] **Step 3: Implement in `settings.py`**

Add the field to `Settings` (after `model_explicitly_set`):
```python
@dataclass
class Settings:
    library_path: Path
    default_model: str
    confidence_floor: float
    learn_mode_hash: str = field(default_factory=lambda: DEFAULT_LEARN_MODE_HASH)
    model_explicitly_set: bool = False
    default_provider: str = "claude"
```

Replace the body of `load_settings` from the `return Settings(...)` onward with a validated build:
```python
    s = Settings(
        library_path=Path(data.get("library_path", str(defaults.library_path))),
        default_model=data.get("default_model", defaults.default_model),
        confidence_floor=float(data.get("confidence_floor", defaults.confidence_floor)),
        learn_mode_hash=data.get("learn_mode_hash", DEFAULT_LEARN_MODE_HASH),
        model_explicitly_set=bool(data.get("model_explicitly_set", False)),
        default_provider=data.get("default_provider", config.DEFAULT_PROVIDER),
    )
    # Guard against a corrupt/hand-edited model/provider mismatch.
    if config.provider_of_model(s.default_model) != s.default_provider:
        s.default_model = config.default_model_for(s.default_provider)
    return s
```

- [ ] **Step 4: Run tests**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_settings.py Dev/kb_chatbot/tests/test_learn_mode.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/settings.py Dev/kb_chatbot/tests/test_settings.py
git commit -m "feat(v2.5): settings default_provider with model/provider validation guard"
```

---

## Task 5: GUI — Provider Dropdown, Notices, Factory, Init, Preflight

**Files:**
- Modify: `Dev/kb_chatbot/gui.py`

No Qt unit tests — verify via import + the existing suite. Surgical edits.

- [ ] **Step 1: Add imports + the provider factory**

In `gui.py`, the LLM import line currently reads:
```python
from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeProvider, ClaudeCodeNotFoundError
```
Add the Codex import on the next line:
```python
from Dev.kb_chatbot.llm.codex_provider import CodexProvider, CodexNotFoundError, codex_login_ok
```
Change the rewriter import from `rewrite_query` to the factory:
```python
from Dev.kb_chatbot.chat.query_rewriter import make_rewriter
```

Add a module-level factory after the imports / constants block (near `THINKING_WORDS`):
```python
def build_provider(provider_id: str):
    """Construct the LLM provider for the given provider id."""
    if provider_id == "openai":
        return CodexProvider()
    return ClaudeCodeProvider()
```

- [ ] **Step 2: Add the AI Provider dropdown + model repopulation in `_build_ui`**

Replace the Model-dropdown portion of `filter_row` (currently builds `self.model_box` from `config.AVAILABLE_MODELS` and selects `self.settings.default_model`) with a Provider + Model pair:

```python
        filter_row.addWidget(QLabel("AI Provider:"))
        self.provider_box = QComboBox()
        for pid, prov in config.PROVIDERS.items():
            self.provider_box.addItem(prov["display"], pid)
        pidx = self.provider_box.findData(self.settings.default_provider)
        if pidx >= 0:
            self.provider_box.setCurrentIndex(pidx)
        filter_row.addWidget(self.provider_box)

        filter_row.addWidget(QLabel("Model:"))
        self.model_box = QComboBox()
        self._populate_model_box(self.settings.default_provider, self.settings.default_model)
        filter_row.addWidget(self.model_box)
```

(Keep the `Product:` widgets above and `filter_row.addStretch()` / `outer.addLayout(filter_row)` below unchanged.)

Wire the change signals in the connect block at the end of `_build_ui` (next to the other `.connect(...)` lines):
```python
        self.provider_box.currentIndexChanged.connect(self._on_provider_changed)
        self.model_box.currentIndexChanged.connect(self._on_model_changed)
```

- [ ] **Step 3: Add the dropdown-management methods to `MainWindow`**

Add an `_suppress_dropdown_notices` flag in `__init__` (right after `self._attachments: list = []`):
```python
        self._suppress_dropdown_notices = True   # silenced until first real user change
```

Add these methods to `MainWindow`:
```python
    def _populate_model_box(self, provider_id: str, select_model: str = ""):
        """Fill the model dropdown for a provider. Silent — sets the suppress
        flag so the programmatic clear/add doesn't post change notices."""
        self._suppress_dropdown_notices = True
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for label, ident in config.models_for(provider_id).items():
            self.model_box.addItem(label, ident)
        target = select_model or config.default_model_for(provider_id)
        idx = self.model_box.findData(target)
        self.model_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.model_box.blockSignals(False)
        self._suppress_dropdown_notices = False

    @Slot(int)
    def _on_provider_changed(self, _index: int):
        provider_id = self.provider_box.currentData()
        self._populate_model_box(provider_id)
        display = config.PROVIDERS[provider_id]["display"]
        model_label = self.model_box.currentText()
        self._append("system", f"⇄ Switched to {display} — model set to {model_label}",
                     "#6a1b9a", "PROVIDER:")
        if provider_id == "openai" and not codex_login_ok():
            self._append("system",
                "Codex CLI is not ready. Install it and run `codex login`, "
                "then try again.", "#c62828", "ERROR:")

    @Slot(int)
    def _on_model_changed(self, _index: int):
        if self._suppress_dropdown_notices:
            return
        self._append("system", f"⇄ Model changed to {self.model_box.currentText()}",
                     "#6a1b9a", "PROVIDER:")
```

- [ ] **Step 4: Rework `_send` to use the selected provider + readiness guard**

Replace the provider-construction block in `_send` (currently `try: llm = ClaudeCodeProvider() except ClaudeCodeNotFoundError ...` and the `Deps(...)` construction) with:

```python
        provider_id = self.provider_box.currentData()
        if provider_id == "openai" and not codex_login_ok():
            self._append("system",
                "Codex CLI is not ready. Install it and run `codex login`, "
                "then try again.", "#c62828", "ERROR:")
            self._set_inputs_enabled(True)
            return
        try:
            llm = build_provider(provider_id)
        except (ClaudeCodeNotFoundError, CodexNotFoundError) as exc:
            self._append("system", str(exc), "#c62828", "ERROR:")
            self._set_inputs_enabled(True)
            return

        deps = Deps(retriever=self._retriever, llm=llm, usage_logger=_append_usage,
                    attachments=attachments, rewriter=make_rewriter(provider_id))
```

(The rest of `_send` — `filters`, `model = self.model_box.currentData()`, worker creation, signal wiring, `self._thinking.start(...)` — is unchanged.)

- [ ] **Step 5: Make `InitWorker` provider-aware**

Change `InitWorker.run` so it warms whichever provider is the default. Replace the warm-up block:
```python
            self.status.emit("⟳ Initialising — loading models…")
            retriever = Retriever(
                config.CHROMA_DIR,
                confidence_floor=self.settings.confidence_floor,
            )
            provider_id = getattr(self.settings, "default_provider", "claude")
            display = config.PROVIDERS.get(provider_id, config.PROVIDERS["claude"])["display"]
            self.status.emit(f"⟳ Initialising — warming up {display}…")
            try:
                if provider_id == "claude":
                    from Dev.kb_chatbot.prompt import build_system_prompt
                    ClaudeCodeProvider().warm_up(build_system_prompt(), self.settings.default_model)
                # Codex exec is cold-start per call — nothing to warm.
            except (ClaudeCodeNotFoundError, CodexNotFoundError) as exc:
                log.warning("Skipping LLM warm-up: %s", exc)
            self.ready.emit(retriever)
```

Generalise `_on_init_status` so the pin matches any provider:
```python
    @Slot(str)
    def _on_init_status(self, msg: str):
        if "warming up" in msg.lower():
            self._init_thinking.pin(msg.split("—", 1)[-1].strip().rstrip("…"))
```

- [ ] **Step 6: Make startup preflight provider-aware**

Replace `_preflight_claude_code` and its use in `main()`:
```python
def _preflight_provider(provider_id: str) -> Optional[str]:
    if provider_id == "openai":
        from Dev.kb_chatbot.llm.codex_provider import codex_login_ok
        if codex_login_ok():
            return None
        return ("Codex CLI is required for ChatGPT.\n\n"
                "Install the Codex CLI and run `codex login`, then re-launch.")
    if shutil.which("claude"):
        return None
    return ("Claude Code is required.\n\n"
            "Install from https://claude.com/claude-code, run `claude login`, "
            "and re-launch this app.")
```
In `main()`, read the saved default provider before constructing the window:
```python
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Contoso KB Chatbot")
    saved = settings_mod.load_settings()
    err = _preflight_provider(saved.default_provider)
    if err:
        QMessageBox.critical(None, "AI provider not ready", err)
        sys.exit(1)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
```
(`settings_mod` is already imported at the top of `gui.py`.)

- [ ] **Step 7: Verify**

```
& "scraper\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, '.'); from Dev.kb_chatbot import gui; print('import OK')"
& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/ -q
```
Expected: import OK; full suite PASS.

- [ ] **Step 8: Commit**

```
git add Dev/kb_chatbot/gui.py
git commit -m "feat(v2.5): AI Provider dropdown, change notices, provider factory, provider-aware init/preflight"
```

---

## Task 6: GUI — SettingsDialog Pair + Token Viewer

**Files:**
- Modify: `Dev/kb_chatbot/gui.py`
- Test: `Dev/kb_chatbot/tests/test_config_providers.py` (extend with a source-inspection guard)

- [ ] **Step 1: SettingsDialog — Provider + Model pair**

In `SettingsDialog.__init__`, replace the single model-box build:
```python
        self.model_box = QComboBox()
        for label, ident in config.AVAILABLE_MODELS.items():
            self.model_box.addItem(label, ident)
        idx = self.model_box.findData(current.default_model)
        if idx >= 0:
            self.model_box.setCurrentIndex(idx)
        form.addRow("Library path:", lib_w)
        form.addRow("Default model:", self.model_box)
```
with a provider + model pair:
```python
        self.provider_box = QComboBox()
        for pid, prov in config.PROVIDERS.items():
            self.provider_box.addItem(prov["display"], pid)
        ppidx = self.provider_box.findData(getattr(current, "default_provider", "claude"))
        if ppidx >= 0:
            self.provider_box.setCurrentIndex(ppidx)
        self.model_box = QComboBox()
        self._fill_models(getattr(current, "default_provider", "claude"), current.default_model)
        self.provider_box.currentIndexChanged.connect(self._on_dialog_provider_changed)
        form.addRow("Library path:", lib_w)
        form.addRow("Default AI provider:", self.provider_box)
        form.addRow("Default model:", self.model_box)
```

Add helper methods to `SettingsDialog`:
```python
    def _fill_models(self, provider_id: str, select_model: str = ""):
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for label, ident in config.models_for(provider_id).items():
            self.model_box.addItem(label, ident)
        idx = self.model_box.findData(select_model or config.default_model_for(provider_id))
        self.model_box.setCurrentIndex(idx if idx >= 0 else 0)
        self.model_box.blockSignals(False)

    def _on_dialog_provider_changed(self, _index: int):
        self._fill_models(self.provider_box.currentData())
```

Update `values()` to persist the provider:
```python
    def values(self):
        return settings_mod.Settings(
            library_path=Path(self.lib_edit.text()),
            default_model=self.model_box.currentData(),
            confidence_floor=config.CONFIDENCE_FLOOR,
            learn_mode_hash=self._current.learn_mode_hash,
            model_explicitly_set=True,
            default_provider=self.provider_box.currentData(),
        )
```

- [ ] **Step 2: TokenUsageDialog — use the shared display map + general footer**

In `TokenUsageDialog`, delete the hardcoded `_MODEL_DISPLAY` class attribute and use `config.MODEL_DISPLAY`. Change the model lookup line:
```python
            model = config.MODEL_DISPLAY.get(r.get("model") or "", r.get("model") or "—")
```
Replace the footer text:
```python
        footer = QLabel(
            "Rates: API-equivalent, Anthropic & OpenAI published pricing (June 2026). "
            "ChatGPT counts include Codex's agent overhead, so they read higher than Claude. "
            "Edit config.COST_TABLE if rates change."
        )
```

- [ ] **Step 3: Add a source-inspection regression test**

Append to `Dev/kb_chatbot/tests/test_config_providers.py`:
```python
def test_gui_settings_dialog_persists_provider():
    import inspect
    from Dev.kb_chatbot import gui
    src = inspect.getsource(gui.SettingsDialog.values)
    assert "default_provider=" in src


def test_gui_has_provider_factory_and_dropdown():
    import inspect
    from Dev.kb_chatbot import gui
    assert hasattr(gui, "build_provider")
    src = inspect.getsource(gui.MainWindow._build_ui)
    assert "AI Provider" in src
```

- [ ] **Step 4: Verify**

```
& "scraper\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, '.'); from Dev.kb_chatbot import gui; print('import OK')"
& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/ -q
```
Expected: import OK; full suite PASS.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/gui.py Dev/kb_chatbot/tests/test_config_providers.py
git commit -m "feat(v2.5): SettingsDialog provider+model pair; token viewer uses shared display map + dual-provider footer"
```

---

## Task 7: Final Integration

- [ ] **Step 1: Full suite**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/ -q`
Expected: all PASS (~170 tests, ~2.5 min).

- [ ] **Step 2: Live smoke test of the real Codex path (one real call)**

This confirms the end-to-end subprocess wiring (the unit tests stub it). Run from the repo root:
```
& "scraper\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0,'.'); from Dev.kb_chatbot.llm.codex_provider import CodexProvider; r=CodexProvider().chat(messages=[{'role':'user','content':'Reply with exactly: pong'}], model='gpt-5.4-mini', system_prompt='You are a test.'); print(repr(r.text), r.input_tokens, r.output_tokens, round(r.cost_estimate_usd,5))"
```
Expected: prints something containing `pong`, a large input-token count (Codex scaffold), a small output count, and a non-zero cost. If `codex` isn't logged in this is expected to raise `CodexNotFoundError`/fail — note it and move on (the user will validate in the walkthrough).

- [ ] **Step 3: Manual walkthrough checklist (user, after exe rebuild)**

1. Launch → default provider Claude, dropdowns show `AI Provider: Claude` / `Model: Sonnet`.
2. Switch AI Provider to **ChatGPT** → model dropdown repopulates to GPT-5.5/5.4/5.4-mini; chat shows `⇄ Switched to ChatGPT — model set to GPT-5.5`.
3. Change model to GPT-5.4-mini → chat shows `⇄ Model changed to GPT-5.4-mini`.
4. Ask a KB question → ChatGPT answers with citations (Codex reasoning over the same retrieved context).
5. Ask the clarification-flow case (post a deal → "TradeDesk") → still resolves (fusion is provider-agnostic).
6. Switch back to Claude → notice posts; Claude answers.
7. Settings → AI provider + model pair persists across relaunch.
8. Settings → View Token Usage → GPT rows appear with model names + costs; footer notes ChatGPT includes Codex overhead.

- [ ] **Step 4: Commit any stragglers; do not merge** (finishing-a-development-branch handles that)
