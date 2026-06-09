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
import sys
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


def _codex_argv(args: list[str]) -> list[str]:
    """Resolve the codex executable to a full path and build the argv. On
    Windows the CLI is an npm shim (codex.CMD/.BAT) which CreateProcess cannot
    launch directly — route those through `cmd /c`. A bare 'codex' string would
    raise FileNotFoundError even though shutil.which finds the shim."""
    exe = _ensure_codex_available()
    if sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat")):
        return ["cmd", "/c", exe, *args]
    return [exe, *args]


_login_ok_cache = False  # once True, stay True for the session (avoid re-probing)


def codex_login_ok() -> bool:
    """True if `codex login status` reports an authenticated account. Runs a
    subprocess, so the first success is cached for the session — the common
    'already logged in' path then costs nothing on the GUI thread. Only a true
    result is cached; a false result is always re-probed so logging in
    mid-session is picked up."""
    global _login_ok_cache
    if _login_ok_cache:
        return True
    if not shutil.which("codex"):
        return False
    try:
        r = subprocess.run(_codex_argv(["login", "status"]),
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return False
    _login_ok_cache = r.returncode == 0
    return _login_ok_cache


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
    out_fd, out_path = tempfile.mkstemp(suffix=".txt", prefix="kbcodex_")
    os.close(out_fd)
    args = ["exec", "-m", model, "--json",
            "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
            "-o", out_path]
    for p in (image_paths or []):
        args += ["-i", p]
    args.append("-")  # read prompt from stdin
    cmd = _codex_argv(args)  # resolves the exe + wraps Windows .CMD shims
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
