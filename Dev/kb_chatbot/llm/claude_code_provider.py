"""ClaudeCodeProvider: persistent ClaudeSDKClient on a dedicated asyncio thread.

The Claude CLI is booted once (when the first turn fires, or earlier if .warm_up()
is called) and reused across every turn — saving the ~2s subprocess cold-start
per question. On Windows, every subprocess spawned by this app gets
CREATE_NO_WINDOW so the cmd window never flashes.
"""
from __future__ import annotations
import asyncio
import logging
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Optional

from Dev.kb_chatbot.llm.base import LLMProvider, LLMResponse, estimate_cost

log = logging.getLogger("kb_chatbot.llm.claude_code")

# ── Subprocess: hide cmd windows on Windows ──────────────────────────────────
_CREATE_NO_WINDOW = 0x08000000
if sys.platform == "win32" and not getattr(subprocess.Popen.__init__, "_kb_hidden", False):
    _orig_popen_init = subprocess.Popen.__init__

    def _hidden_popen_init(self, *args, **kwargs):
        flags = kwargs.get("creationflags", 0) or 0
        kwargs["creationflags"] = flags | _CREATE_NO_WINDOW
        return _orig_popen_init(self, *args, **kwargs)

    _hidden_popen_init._kb_hidden = True  # type: ignore[attr-defined]
    subprocess.Popen.__init__ = _hidden_popen_init  # type: ignore[method-assign]


class ClaudeCodeNotFoundError(RuntimeError):
    """Raised when the `claude` CLI cannot be located on PATH."""


def _ensure_claude_available() -> str:
    path = shutil.which("claude")
    if not path:
        raise ClaudeCodeNotFoundError(
            "Claude Code CLI not found on PATH. Install from https://claude.com/claude-code "
            "and run `claude login` once, then re-launch this app."
        )
    return path


def _build_user_prompt(messages: list[dict]) -> str:
    """Format a full message list as a single role-tagged string for the SDK query."""
    parts = []
    for m in messages:
        role = m.get("role", "user").upper()
        content = m.get("content", "")
        if isinstance(content, list):
            # Multimodal: extract text blocks only for history formatting
            text_parts = [b.get("text", "") for b in content if b.get("type") == "text"]
            content = " ".join(text_parts)
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


# ── Async backend: one daemon thread runs one asyncio loop ───────────────────
class _AsyncBackend:
    """Owns an asyncio event loop on a dedicated daemon thread. Submit
    coroutines via .submit(coro) and the call blocks until the result is ready."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        loop_ready = threading.Event()

        def _run() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            loop_ready.set()
            try:
                self._loop.run_forever()
            finally:
                try:
                    self._loop.close()
                except Exception:
                    pass

        self._thread = threading.Thread(target=_run, name="claude-sdk-loop", daemon=True)
        self._thread.start()
        if not loop_ready.wait(timeout=5):
            raise RuntimeError("Failed to start ClaudeCodeProvider async backend loop")
        assert self._loop is not None

    def submit(self, coro) -> Any:
        """Run a coroutine on the backend loop; block this thread until done."""
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def submit_nowait(self, coro) -> None:
        """Fire-and-forget: schedule a coroutine on the loop, return immediately."""
        assert self._loop is not None
        asyncio.run_coroutine_threadsafe(coro, self._loop)

    def close(self) -> None:
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)


# ── Provider ─────────────────────────────────────────────────────────────────
class ClaudeCodeProvider(LLMProvider):
    """Uses a persistent ClaudeSDKClient on a dedicated asyncio loop thread."""

    # Class-level singletons — shared across all provider instances within one
    # process, so each turn creates a cheap wrapper while the heavy resources
    # (backend thread + SDK client) live as long as the app.
    _backend: Optional[_AsyncBackend] = None
    _client: Any = None
    _client_signature: tuple = ()  # (system_prompt, model) — rebuild if it changes
    _lock = threading.Lock()

    def __init__(self) -> None:
        _ensure_claude_available()
        with ClaudeCodeProvider._lock:
            if ClaudeCodeProvider._backend is None:
                ClaudeCodeProvider._backend = _AsyncBackend()

    # ── Lifecycle ────────────────────────────────────────────────────────────
    def warm_up(self, system_prompt: str, model: str) -> None:
        """Fire-and-forget: pre-build the SDK client so the first real chat is
        fast. Safe to call multiple times; no-ops if the client is already up
        with a matching signature."""
        backend = ClaudeCodeProvider._backend
        if backend is None:
            return
        backend.submit_nowait(self._ensure_client(system_prompt, model))

    @classmethod
    def shutdown(cls) -> None:
        """Close the persistent client + backend. Call on app exit."""
        with cls._lock:
            if cls._client is not None and cls._backend is not None:
                try:
                    cls._backend.submit(cls._aexit_client())
                except Exception:
                    log.exception("Error closing ClaudeSDKClient")
                cls._client = None
                cls._client_signature = ()
            if cls._backend is not None:
                cls._backend.close()
                cls._backend = None

    @classmethod
    async def _aexit_client(cls) -> None:
        if cls._client is not None:
            try:
                await cls._client.__aexit__(None, None, None)
            except Exception:
                log.exception("ClaudeSDKClient __aexit__ raised")

    # ── Chat ─────────────────────────────────────────────────────────────────
    def chat(self, *, messages, model, system_prompt, max_tokens=1024) -> LLMResponse:
        started = time.time()
        backend = ClaudeCodeProvider._backend
        if backend is None:
            raise RuntimeError("ClaudeCodeProvider backend not initialised")
        text, in_tok, out_tok = backend.submit(
            self._query_persistent(messages, model, system_prompt)
        )
        latency_ms = int((time.time() - started) * 1000)
        return LLMResponse(
            text=text,
            input_tokens=in_tok,
            output_tokens=out_tok,
            model=model,
            latency_ms=latency_ms,
            cost_estimate_usd=estimate_cost(model, in_tok, out_tok),
        )

    async def _ensure_client(self, system_prompt: str, model: str) -> None:
        """Create the SDK client if missing, or rebuild it if system_prompt /
        model changed. Runs on the backend loop thread — serialised by design."""
        from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions
        cls = ClaudeCodeProvider
        signature = (system_prompt, model)
        if cls._client is not None and cls._client_signature == signature:
            return
        if cls._client is not None:
            try:
                await cls._client.__aexit__(None, None, None)
            except Exception:
                log.exception("Error tearing down stale ClaudeSDKClient")
            cls._client = None
            cls._client_signature = ()
        options = ClaudeAgentOptions(system_prompt=system_prompt, model=model)
        cls._client = ClaudeSDKClient(options=options)
        await cls._client.__aenter__()
        cls._client_signature = signature
        log.info("ClaudeSDKClient booted (model=%s)", model)

    async def _query_persistent(self, messages: list[dict], model: str, system_prompt: str) -> tuple[str, int, int]:
        await self._ensure_client(system_prompt, model)
        prompt = _build_user_prompt(messages)
        cls = ClaudeCodeProvider
        await cls._client.query(prompt)

        text_parts: list[str] = []
        in_tok = 0
        out_tok = 0
        async for message in cls._client.receive_response():
            content = getattr(message, "content", None)
            if content:
                for block in content:
                    block_text = getattr(block, "text", None)
                    if block_text:
                        text_parts.append(block_text)
            usage = getattr(message, "usage", None)
            if usage:
                in_tok = max(in_tok, getattr(usage, "input_tokens", in_tok) or in_tok)
                out_tok = max(out_tok, getattr(usage, "output_tokens", out_tok) or out_tok)

        text = "".join(text_parts).strip()
        if not in_tok and not out_tok:
            in_tok = max(1, len(prompt) // 4)
            out_tok = max(1, len(text) // 4)
        return text, in_tok, out_tok
