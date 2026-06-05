"""Stateless one-shot query rewriting via the Claude Code CLI.

Uses the SDK's module-level query() — a fresh subprocess per call — so the
persistent chat session's history is never polluted. Called only as an
escalation when post-fusion retrieval abstains (max once per turn), so the
~2s subprocess cost replaces a turn that would otherwise fail outright."""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

# Importing the provider applies the Windows hidden-subprocess patch
from Dev.kb_chatbot.llm import claude_code_provider as _provider  # noqa: F401

log = logging.getLogger("kb_chatbot.query_rewriter")

REWRITE_MODEL = "claude-haiku-4-5-20251001"

REWRITE_SYSTEM_PROMPT = (
    "You rewrite a user's conversational message into ONE standalone search query "
    "for a product documentation knowledge base (Contoso: TradeDesk, API, Web2, "
    "Web4, SalesHub). Use the conversation to resolve references like 'that' or "
    "short answers to clarifying questions. Reply with the search query only — "
    "no quotes, no explanation, max 20 words."
)

_HISTORY_WINDOW = 4  # last 2 user/assistant exchanges


@dataclass
class RewriteResult:
    query: str
    tokens_in: int
    tokens_out: int
    latency_ms: int


def build_rewrite_prompt(user_msg: str, history: list[dict]) -> str:
    lines = ["Conversation:"]
    for m in history[-_HISTORY_WINDOW:]:
        content = m.get("content", "")
        if isinstance(content, list):
            content = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
        lines.append(f"{m.get('role', 'user').upper()}: {content}")
    lines.append(f"LATEST MESSAGE: {user_msg}")
    lines.append("Standalone search query:")
    return "\n".join(lines)


def _usage_value(usage, key: str) -> int:
    """Read a token count from the SDK usage payload, which is a plain dict
    (dict[str, Any] | None) — attribute access would silently return 0."""
    if isinstance(usage, dict):
        return int(usage.get(key, 0) or 0)
    return int(getattr(usage, key, 0) or 0)


def _clean_response(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return ""
    return stripped.splitlines()[0].strip().strip('"').strip()


def rewrite_query(user_msg: str, history: list[dict]) -> Optional[RewriteResult]:
    """One stateless rewrite call. Returns None on any failure — the caller
    falls back to the fused query; a rewrite failure must never break a turn."""
    started = time.time()
    try:
        text, tin, tout = asyncio.run(_run_query(build_rewrite_prompt(user_msg, history)))
    except Exception:
        log.exception("Query rewrite failed (non-fatal)")
        return None
    query = _clean_response(text)
    if not query:
        return None
    return RewriteResult(query=query, tokens_in=tin, tokens_out=tout,
                         latency_ms=int((time.time() - started) * 1000))


async def _run_query(prompt: str) -> tuple[str, int, int]:
    from claude_agent_sdk import query, ClaudeAgentOptions
    options = ClaudeAgentOptions(system_prompt=REWRITE_SYSTEM_PROMPT, model=REWRITE_MODEL)
    text_parts: list[str] = []
    tin = tout = 0
    async for message in query(prompt=prompt, options=options):
        content = getattr(message, "content", None)
        if content:
            for block in content:
                bt = getattr(block, "text", None)
                if bt:
                    text_parts.append(bt)
        usage = getattr(message, "usage", None)
        if usage:
            # The final ResultMessage carries authoritative cumulative totals;
            # max() keeps the largest seen across all message types.
            tin = max(tin, _usage_value(usage, "input_tokens"))
            tout = max(tout, _usage_value(usage, "output_tokens"))
    text = "".join(text_parts)
    if not tin and not tout:
        tin = max(1, len(prompt) // 4)
        tout = max(1, len(text) // 4)
    return text, tin, tout
