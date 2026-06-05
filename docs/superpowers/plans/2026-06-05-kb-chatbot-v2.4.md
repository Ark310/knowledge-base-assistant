# KB Chatbot v2.4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix clarification-flow context loss with retrieval fusion + stateless LLM rewrite escalation, add a Claude-style thinking animation, default to Sonnet, and add a token usage & cost viewer.

**Architecture:** All retrieval-side intelligence lives in the orchestrator (fusion) and a new stateless `query_rewriter` module (escalation). GUI gains a `ThinkingIndicator` widget and a `TokenUsageDialog` backed by a new pure `usage_stats` module. The retriever, chunker, ingest, citations, prompt, and persistent LLM provider are untouched.

**Tech Stack:** PySide6, claude-agent-sdk (module-level `query()` for stateless calls), Python 3.12

**Working directory:** repo root. **Branch:** `feature/kb-chatbot-v2.4`. **Test command:** `& "scraper\venv\Scripts\python.exe" -m pytest <path> -v`

---

## File Map

| File | Status | Responsibility |
|------|--------|----------------|
| `Dev/kb_chatbot/chat/session.py` | Modify | Add `last_user_question()`, `last_assistant_kind()` read-only helpers |
| `Dev/kb_chatbot/chat/orchestrator.py` | Modify | Fusion (`_build_retrieval_query`), escalation path, `Deps.rewriter`/`Deps.on_progress`, rewrite usage logging |
| `Dev/kb_chatbot/chat/query_rewriter.py` | **New** | Stateless one-shot rewrite via module-level SDK `query()` |
| `Dev/kb_chatbot/usage_stats.py` | **New** | Pure usage.jsonl loading/summarising/cost functions |
| `Dev/kb_chatbot/config.py` | Modify | `DEFAULT_MODEL` → Sonnet |
| `Dev/kb_chatbot/settings.py` | Modify | `model_explicitly_set` field + `migrate_default_model()` |
| `Dev/kb_chatbot/gui.py` | Modify | `ThinkingIndicator`, progress signal, migration notice, `TokenUsageDialog`, Settings button |
| `Dev/kb_chatbot/tests/test_query_fusion.py` | **New** | Fusion unit tests |
| `Dev/kb_chatbot/tests/test_query_rewriter.py` | **New** | Rewrite prompt/result + escalation tests |
| `Dev/kb_chatbot/tests/test_usage_stats.py` | **New** | usage_stats tests |
| `Dev/kb_chatbot/tests/test_settings.py` | Extend | Migration matrix tests |

---

## Task 1: Session History Helpers

**Files:**
- Modify: `Dev/kb_chatbot/chat/session.py`
- Test: `Dev/kb_chatbot/tests/test_query_fusion.py` (create)

- [ ] **Step 1: Write failing tests**

Create `Dev/kb_chatbot/tests/test_query_fusion.py`:

```python
from Dev.kb_chatbot.chat.session import Session, Turn


def _session_with(*turns) -> Session:
    s = Session.new()
    for role, content, kind in turns:
        if role == "user":
            s.add_user(content)
        else:
            s.add(Turn(role="assistant", content=content, kind=kind))
    return s


def test_last_user_question_empty_session():
    assert Session.new().last_user_question() == ""


def test_last_user_question_returns_newest():
    s = _session_with(("user", "first q", "user"),
                      ("assistant", "answer", "answer"),
                      ("user", "second q", "user"))
    assert s.last_user_question() == "second q"


def test_last_assistant_kind_empty_session():
    assert Session.new().last_assistant_kind() == ""


def test_last_assistant_kind_returns_newest():
    s = _session_with(("user", "q", "user"),
                      ("assistant", "which product?", "clarification"))
    assert s.last_assistant_kind() == "clarification"


def test_last_assistant_kind_skips_user_turns():
    s = _session_with(("user", "q", "user"),
                      ("assistant", "ans", "answer"),
                      ("user", "follow", "user"))
    assert s.last_assistant_kind() == "answer"
```

- [ ] **Step 2: Run to verify failure**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_query_fusion.py -v`
Expected: AttributeError — `Session` has no `last_user_question`.

- [ ] **Step 3: Implement**

Add to the `Session` class in `Dev/kb_chatbot/chat/session.py` (after `history_for_llm`):

```python
    def last_user_question(self) -> str:
        """Newest user message content, or '' if none."""
        for t in reversed(self.turns):
            if t.get("role") == "user":
                return t.get("content", "")
        return ""

    def last_assistant_kind(self) -> str:
        """Kind of the newest assistant turn ('answer'/'clarification'/'abstain'), or ''."""
        for t in reversed(self.turns):
            if t.get("role") == "assistant":
                return t.get("kind", "")
        return ""
```

- [ ] **Step 4: Run to verify pass**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_query_fusion.py -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/chat/session.py Dev/kb_chatbot/tests/test_query_fusion.py
git commit -m "feat(v2.4): add last_user_question/last_assistant_kind session helpers"
```

---

## Task 2: Retrieval Query Fusion

**Files:**
- Modify: `Dev/kb_chatbot/chat/orchestrator.py`
- Test: `Dev/kb_chatbot/tests/test_query_fusion.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `Dev/kb_chatbot/tests/test_query_fusion.py`:

```python
from Dev.kb_chatbot.chat.orchestrator import _build_retrieval_query, _extract_single_product


def test_extract_single_product():
    assert _extract_single_product("TradeDesk please") == "tradedesk"
    assert _extract_single_product("the api one") == "api"


def test_extract_no_product():
    assert _extract_single_product("the first option") is None


def test_extract_multiple_products_returns_none():
    assert _extract_single_product("tradedesk or web2?") is None


def test_fusion_raw_passthrough_no_history():
    s = Session.new()
    q, product = _build_retrieval_query(s, "How do I post a deal?")
    assert q == "How do I post a deal?"
    assert product is None


def test_fusion_clarification_reply_combines_and_extracts_product():
    s = _session_with(("user", "How do I post a deal?", "user"),
                      ("assistant", "Which product?", "clarification"))
    q, product = _build_retrieval_query(s, "TradeDesk")
    assert q == "How do I post a deal? TradeDesk"
    assert product == "tradedesk"


def test_fusion_clarification_reply_without_product():
    s = _session_with(("user", "How do I post a deal?", "user"),
                      ("assistant", "Which product?", "clarification"))
    q, product = _build_retrieval_query(s, "the retail one")
    assert q == "How do I post a deal? the retail one"
    assert product is None


def test_fusion_short_followup_combines():
    s = _session_with(("user", "How do I post a deal in TradeDesk?", "user"),
                      ("assistant", "Steps: ...", "answer"))
    q, product = _build_retrieval_query(s, "how to reverse it?")
    assert q == "How do I post a deal in TradeDesk? how to reverse it?"
    assert product is None


def test_fusion_long_message_passthrough():
    s = _session_with(("user", "How do I post a deal?", "user"),
                      ("assistant", "Steps: ...", "answer"))
    msg = "What are the compliance requirements for posting a new retail deal?"
    q, product = _build_retrieval_query(s, msg)
    assert q == msg
    assert product is None
```

- [ ] **Step 2: Run to verify failure**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_query_fusion.py -v`
Expected: ImportError — `_build_retrieval_query` not defined.

- [ ] **Step 3: Implement in `orchestrator.py`**

Add after `_is_topic_drift` (uses the existing `config` import):

```python
_FOLLOW_UP_WORD_LIMIT = 5


def _extract_single_product(text: str) -> Optional[str]:
    """Product slug if the text names exactly one product, else None."""
    low = text.lower()
    found = [p for p in config.PRODUCTS if p in low]
    return found[0] if len(found) == 1 else None


def _build_retrieval_query(session: Session, user_msg: str) -> tuple[str, Optional[str]]:
    """Fuse short replies with the prior question so retrieval sees full context.

    Returns (retrieval_query, extracted_product). Must be called BEFORE
    session.add_user(user_msg) so last_user_question() is the prior question.
    The raw user_msg is what the LLM sees; fusion affects retrieval only."""
    prev_q = session.last_user_question()
    if not prev_q:
        return user_msg, None
    if session.last_assistant_kind() == "clarification":
        return f"{prev_q} {user_msg}", _extract_single_product(user_msg)
    if len(user_msg.strip().split()) < _FOLLOW_UP_WORD_LIMIT:
        return f"{prev_q} {user_msg}", None
    return user_msg, None
```

- [ ] **Step 4: Wire into `handle_turn`**

In `handle_turn`, replace the opening lines:

```python
def handle_turn(user_msg: str, session: Session, filters: Filters,
                default_model: str, *, deps: Deps) -> Turn:
    history = session.history_for_llm(config.MAX_HISTORY_TURNS)
    session.add_user(user_msg)

    result = deps.retriever.retrieve(user_msg, filters)
```

with:

```python
def handle_turn(user_msg: str, session: Session, filters: Filters,
                default_model: str, *, deps: Deps) -> Turn:
    history = session.history_for_llm(config.MAX_HISTORY_TURNS)
    retrieval_query, extracted_product = _build_retrieval_query(session, user_msg)
    fused = retrieval_query != user_msg
    if extracted_product and not filters.product:
        filters = Filters(product=extracted_product,
                          version_min=filters.version_min,
                          version_max=filters.version_max)
    session.add_user(user_msg)

    result = deps.retriever.retrieve(retrieval_query, filters)
```

Then update the remaining uses of the query inside `handle_turn`:
- Both `deps.retriever.retrieve_quick(user_msg, limit=10)` calls → `deps.retriever.retrieve_quick(retrieval_query, limit=10)`
- Both `deps.retriever.suggest(user_msg, top_k=3)` calls → `deps.retriever.suggest(retrieval_query, top_k=3)` (Task 4 refines the abstain-path one further)
- The short-query clarification guard becomes fusion-aware (the user already supplied context):

```python
    if not fused and _is_short_unspecified_query(user_msg):
```

The LLM call's `user_msg=user_msg + drift_note` stays on the RAW message — do not change it.

- [ ] **Step 5: Run fusion tests + orchestrator tests**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_query_fusion.py Dev/kb_chatbot/tests/test_orchestrator.py -v`
Expected: all PASS (orchestrator tests use single-turn sessions where fusion is a no-op, except verify none regress).

- [ ] **Step 6: Commit**

```
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_query_fusion.py
git commit -m "feat(v2.4): retrieval query fusion for clarification replies and short follow-ups"
```

---

## Task 3: Stateless Query Rewriter

**Files:**
- Create: `Dev/kb_chatbot/chat/query_rewriter.py`
- Test: `Dev/kb_chatbot/tests/test_query_rewriter.py` (create)

- [ ] **Step 1: Write failing tests**

Create `Dev/kb_chatbot/tests/test_query_rewriter.py`:

```python
from Dev.kb_chatbot.chat.query_rewriter import (
    build_rewrite_prompt, RewriteResult, REWRITE_MODEL, _clean_response,
)


def test_rewrite_model_is_haiku():
    assert "haiku" in REWRITE_MODEL


def test_prompt_includes_history_and_message():
    history = [
        {"role": "user", "content": "How do I post a deal?"},
        {"role": "assistant", "content": "Which product?"},
    ]
    prompt = build_rewrite_prompt("TradeDesk", history)
    assert "How do I post a deal?" in prompt
    assert "Which product?" in prompt
    assert "TradeDesk" in prompt
    assert "USER:" in prompt and "ASSISTANT:" in prompt


def test_prompt_limits_history_to_last_four_messages():
    history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    prompt = build_rewrite_prompt("latest", history)
    assert "msg5" not in prompt
    assert "msg9" in prompt


def test_prompt_flattens_multimodal_content():
    history = [{"role": "user", "content": [
        {"type": "image", "source": {}},
        {"type": "text", "text": "what is this error"},
    ]}]
    prompt = build_rewrite_prompt("follow up", history)
    assert "what is this error" in prompt


def test_clean_response_strips_quotes_and_extra_lines():
    assert _clean_response('"posting a retail deal tradedesk"\nextra') == "posting a retail deal tradedesk"


def test_clean_response_empty_returns_empty():
    assert _clean_response("   \n  ") == ""


def test_rewrite_result_fields():
    r = RewriteResult(query="q", tokens_in=10, tokens_out=5, latency_ms=100)
    assert (r.query, r.tokens_in, r.tokens_out, r.latency_ms) == ("q", 10, 5, 100)
```

- [ ] **Step 2: Run to verify failure**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_query_rewriter.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Create `Dev/kb_chatbot/chat/query_rewriter.py`**

Before writing, READ `scraper/venv/Lib/site-packages/claude_agent_sdk/query.py` and `types.py` to confirm the module-level `query(prompt=..., options=ClaudeAgentOptions(...))` signature and whether `ClaudeAgentOptions` accepts `max_turns` — if it doesn't, omit that kwarg.

```python
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
            tin = max(tin, getattr(usage, "input_tokens", 0) or 0)
            tout = max(tout, getattr(usage, "output_tokens", 0) or 0)
    text = "".join(text_parts)
    if not tin and not tout:
        tin = max(1, len(prompt) // 4)
        tout = max(1, len(text) // 4)
    return text, tin, tout
```

- [ ] **Step 4: Run to verify pass**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_query_rewriter.py -v`
Expected: 7 PASSED. (The subprocess path is intentionally not unit-tested.)

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/chat/query_rewriter.py Dev/kb_chatbot/tests/test_query_rewriter.py
git commit -m "feat(v2.4): add stateless LLM query rewriter module"
```

---

## Task 4: Orchestrator Escalation Path

**Files:**
- Modify: `Dev/kb_chatbot/chat/orchestrator.py`
- Test: `Dev/kb_chatbot/tests/test_query_rewriter.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `Dev/kb_chatbot/tests/test_query_rewriter.py` (mirror the `deps_factory` stub style from `test_orchestrator.py` — read it first):

```python
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from Dev.kb_chatbot.chat.session import Session, Turn
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps
from Dev.kb_chatbot.retriever import Retriever, Filters, RetrievalResult
from Dev.kb_chatbot.llm.fake_provider import FakeProvider
from Dev.kb_chatbot.chunker import Chunk


def _ctx_chunk():
    return Chunk(id="c1", text="Deal reversal steps",
                 metadata={"product": "tradedesk", "category": "dealing",
                           "title": "Reverse a Deal", "url": "https://x.com/rev"})


def _mock_retriever(results):
    """Retriever whose retrieve() pops from `results` per call."""
    with patch("Dev.kb_chatbot.retriever.chromadb.PersistentClient"), \
         patch("Dev.kb_chatbot.retriever.SentenceTransformer"), \
         patch("Dev.kb_chatbot.retriever.CrossEncoder"):
        r = Retriever(Path("fake"))
    calls = []
    def retrieve(query, filters):
        calls.append(query)
        return results.pop(0)
    r.retrieve = retrieve
    r.retrieve_quick = lambda q, limit=10: []
    r.suggest = lambda q, top_k=5: []
    r._retrieve_calls = calls
    return r


def _session_with_history():
    s = Session.new()
    s.add_user("How do I post a deal in TradeDesk?")
    s.add(Turn(role="assistant", content="Steps...", kind="answer"))
    return s


def test_rewriter_fires_on_abstain_with_history():
    abstain = RetrievalResult(abstain_reason="no_relevant_kb_match", rerank_top_score=0.1)
    success = RetrievalResult(chunks=[_ctx_chunk()], rerank_top_score=0.8)
    r = _mock_retriever([abstain, success])
    rewriter_calls = []
    def fake_rewriter(msg, history):
        rewriter_calls.append(msg)
        from Dev.kb_chatbot.chat.query_rewriter import RewriteResult
        return RewriteResult(query="reverse posted deal tradedesk", tokens_in=200, tokens_out=20, latency_ms=900)
    logged = []
    deps = Deps(retriever=r, llm=FakeProvider(canned_text="Done. [Reverse a Deal](https://x.com/rev)"),
                usage_logger=logged.append, rewriter=fake_rewriter)
    session = _session_with_history()
    turn = handle_turn("undo entire posting flow somehow broken", session, Filters(),
                       "claude-haiku-4-5-20251001", deps=deps)
    assert turn.kind == "answer"
    assert rewriter_calls == ["undo entire posting flow somehow broken"]
    assert r._retrieve_calls[1] == "reverse posted deal tradedesk"
    rewrite_logs = [t for t in logged if t.kind == "rewrite"]
    assert len(rewrite_logs) == 1
    assert rewrite_logs[0].tokens_in == 200


def test_rewriter_not_called_without_history():
    abstain = RetrievalResult(abstain_reason="no_relevant_kb_match", rerank_top_score=0.1)
    r = _mock_retriever([abstain])
    rewriter = MagicMock()
    deps = Deps(retriever=r, llm=FakeProvider(canned_text="x"),
                usage_logger=lambda t: None, rewriter=rewriter)
    turn = handle_turn("some unfindable question here", Session.new(), Filters(),
                       "claude-haiku-4-5-20251001", deps=deps)
    assert turn.kind == "abstain"
    rewriter.assert_not_called()


def test_rewriter_failure_falls_through_to_abstain():
    abstain = RetrievalResult(abstain_reason="no_relevant_kb_match", rerank_top_score=0.1)
    r = _mock_retriever([abstain])
    deps = Deps(retriever=r, llm=FakeProvider(canned_text="x"),
                usage_logger=lambda t: None, rewriter=lambda m, h: None)
    turn = handle_turn("some unfindable question here", _session_with_history(), Filters(),
                       "claude-haiku-4-5-20251001", deps=deps)
    assert turn.kind == "abstain"
    assert len(r._retrieve_calls) == 1  # no retry without a rewrite


def test_rewriter_fires_at_most_once():
    abstain = RetrievalResult(abstain_reason="no_relevant_kb_match", rerank_top_score=0.1)
    r = _mock_retriever([abstain, abstain])
    rewriter = MagicMock(return_value=None)
    from Dev.kb_chatbot.chat.query_rewriter import RewriteResult
    rewriter.return_value = RewriteResult(query="better query", tokens_in=1, tokens_out=1, latency_ms=1)
    deps = Deps(retriever=r, llm=FakeProvider(canned_text="x"),
                usage_logger=lambda t: None, rewriter=rewriter)
    turn = handle_turn("some unfindable question here", _session_with_history(), Filters(),
                       "claude-haiku-4-5-20251001", deps=deps)
    assert turn.kind == "abstain"
    assert rewriter.call_count == 1
    assert len(r._retrieve_calls) == 2


def test_progress_callback_invoked_on_rewrite():
    abstain = RetrievalResult(abstain_reason="no_relevant_kb_match", rerank_top_score=0.1)
    success = RetrievalResult(chunks=[_ctx_chunk()], rerank_top_score=0.8)
    r = _mock_retriever([abstain, success])
    from Dev.kb_chatbot.chat.query_rewriter import RewriteResult
    stages = []
    deps = Deps(retriever=r, llm=FakeProvider(canned_text="x"),
                usage_logger=lambda t: None,
                rewriter=lambda m, h: RewriteResult(query="q2", tokens_in=1, tokens_out=1, latency_ms=1),
                on_progress=stages.append)
    handle_turn("some unfindable question here", _session_with_history(), Filters(),
                "claude-haiku-4-5-20251001", deps=deps)
    assert "rephrase" in stages
```

- [ ] **Step 2: Run to verify failure**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_query_rewriter.py -v`
Expected: TypeError — `Deps` has no `rewriter`/`on_progress` fields.

- [ ] **Step 3: Implement in `orchestrator.py`**

Extend `Deps`:

```python
@dataclass
class Deps:
    retriever: Retriever
    llm: LLMProvider
    usage_logger: Callable[[Turn], None] = lambda t: None
    clarifier: Optional[Callable[[str, list[Chunk]], str]] = None
    attachments: list = field(default_factory=list)
    rewriter: Optional[Callable[[str, list[dict]], "object"]] = None
    on_progress: Callable[[str], None] = lambda stage: None
```

In `handle_turn`, immediately after `result = deps.retriever.retrieve(retrieval_query, filters)` and BEFORE the topic-drift block, add:

```python
    # Escalation: one stateless LLM rewrite when post-fusion retrieval abstains
    # and there is conversation context to rewrite from.
    if result.abstain_reason and deps.rewriter is not None and history:
        deps.on_progress("rephrase")
        rw = deps.rewriter(user_msg, history)
        if rw is not None:
            deps.usage_logger(Turn(
                role="system", kind="rewrite", content=rw.query,
                model=_REWRITE_MODEL_NAME, tokens_in=rw.tokens_in,
                tokens_out=rw.tokens_out, latency_ms=rw.latency_ms,
            ))
            retrieval_query = rw.query
            result = deps.retriever.retrieve(retrieval_query, filters)
```

Add near the other constants:

```python
_REWRITE_MODEL_NAME = "claude-haiku-4-5-20251001"
```

(The rewrite Turn is usage-logged but never `session.add`ed — it must not enter the conversation.)

Because `retrieval_query` is reassigned, the abstain path's `suggest(retrieval_query, top_k=3)` automatically uses the rewritten query. Verify both `suggest` calls and both `retrieve_quick` calls use `retrieval_query` (done in Task 2).

- [ ] **Step 4: Run tests**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_query_rewriter.py Dev/kb_chatbot/tests/test_query_fusion.py Dev/kb_chatbot/tests/test_orchestrator.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_query_rewriter.py
git commit -m "feat(v2.4): LLM rewrite escalation on post-fusion abstain"
```

---

## Task 5: usage_stats Module

**Files:**
- Create: `Dev/kb_chatbot/usage_stats.py`
- Test: `Dev/kb_chatbot/tests/test_usage_stats.py` (create)

- [ ] **Step 1: Write failing tests**

Create `Dev/kb_chatbot/tests/test_usage_stats.py`:

```python
import json
import tempfile
from pathlib import Path

from Dev.kb_chatbot.usage_stats import load_usage, summarize, cost_for, UsageSummary


HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"


def _rec(ts, kind="answer", model=HAIKU, tin=1000, tout=100):
    return {"ts": ts, "kind": kind, "model": model, "tokens_in": tin, "tokens_out": tout}


def _write(path, records, garbage_line=False):
    lines = [json.dumps(r) for r in records]
    if garbage_line:
        lines.insert(1, "{not valid json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_cost_for_haiku():
    # 1M in @ $1 + 1M out @ $5
    assert cost_for({"model": HAIKU, "tokens_in": 1_000_000, "tokens_out": 1_000_000}) == 6.0


def test_cost_for_sonnet():
    assert cost_for({"model": SONNET, "tokens_in": 1_000_000, "tokens_out": 1_000_000}) == 18.0


def test_cost_for_unknown_model_is_zero():
    assert cost_for({"model": "mystery-model", "tokens_in": 999, "tokens_out": 999}) == 0.0


def test_cost_for_missing_model_is_zero():
    assert cost_for({"tokens_in": 100, "tokens_out": 100}) == 0.0


def test_load_skips_malformed_lines():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "usage.jsonl"
        _write(p, [_rec("2026-06-05T10:00:00"), _rec("2026-06-05T10:01:00")], garbage_line=True)
        assert len(load_usage(p)) == 2


def test_load_missing_file_returns_empty():
    assert load_usage(Path("does/not/exist.jsonl")) == []


def test_load_excludes_failed_auth_records():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "usage.jsonl"
        _write(p, [_rec("2026-06-05T10:00:00"),
                   {"kind": "learn_mode_failed_auth", "ts": "2026-06-05T10:02:00"}])
        records = load_usage(p)
        assert len(records) == 1


def test_summarize_splits_session_window():
    records = [
        _rec("2026-06-05T09:00:00", tin=2000, tout=200),   # before session
        _rec("2026-06-05T11:00:00", tin=1000, tout=100),   # in session
        _rec("2026-06-05T11:05:00", kind="rewrite", tin=300, tout=30),  # in session
    ]
    s = summarize(records, session_start="2026-06-05T10:30:00")
    assert s.total_in == 3300 and s.total_out == 330
    assert s.session_in == 1300 and s.session_out == 130
    assert s.total_queries == 3 and s.session_queries == 2
    assert s.total_cost > s.session_cost > 0


def test_summarize_zero_token_rows_not_counted_as_queries():
    records = [
        _rec("2026-06-05T11:00:00"),
        {"ts": "2026-06-05T11:01:00", "kind": "clarification", "model": None,
         "tokens_in": 0, "tokens_out": 0},
    ]
    s = summarize(records, session_start="2026-06-05T10:00:00")
    assert s.total_queries == 1


def test_summarize_empty():
    s = summarize([], session_start="2026-06-05T10:00:00")
    assert s == UsageSummary(0, 0, 0.0, 0, 0, 0, 0.0, 0)
```

- [ ] **Step 2: Run to verify failure**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_usage_stats.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Create `Dev/kb_chatbot/usage_stats.py`**

```python
"""Pure aggregation over state/usage.jsonl for the token usage viewer.

Costs are computed at display time from config.COST_TABLE so editing a rate
reprices all history. No I/O besides reading the jsonl; no network."""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from Dev.kb_chatbot import config

log = logging.getLogger("kb_chatbot.usage_stats")

_EXCLUDED_KINDS = {"learn_mode_failed_auth"}


@dataclass(frozen=True)
class UsageSummary:
    total_in: int
    total_out: int
    total_cost: float
    total_queries: int
    session_in: int
    session_out: int
    session_cost: float
    session_queries: int


def cost_for(record: dict) -> float:
    """API-equivalent USD cost of one usage record. Unknown model → 0.0."""
    rates = config.COST_TABLE.get(record.get("model") or "")
    if not rates:
        return 0.0
    return (record.get("tokens_in", 0) * rates["in"]
            + record.get("tokens_out", 0) * rates["out"]) / 1_000_000


def load_usage(path: Path) -> list[dict]:
    """All usage records, oldest first. Malformed lines and auth-failure
    records are skipped; a missing file is an empty history."""
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            log.warning("Skipping malformed usage line")
            continue
        if rec.get("kind") in _EXCLUDED_KINDS:
            continue
        records.append(rec)
    return records


def summarize(records: list[dict], *, session_start: str = "") -> UsageSummary:
    """Aggregate totals; ISO-string ts comparison is safe (lexicographic).
    'Queries' counts records that actually consumed tokens."""
    total_in = total_out = total_q = 0
    sess_in = sess_out = sess_q = 0
    total_cost = sess_cost = 0.0
    for r in records:
        tin = r.get("tokens_in", 0) or 0
        tout = r.get("tokens_out", 0) or 0
        cost = cost_for(r)
        total_in += tin
        total_out += tout
        total_cost += cost
        if tin + tout > 0:
            total_q += 1
        if session_start and (r.get("ts") or "") >= session_start:
            sess_in += tin
            sess_out += tout
            sess_cost += cost
            if tin + tout > 0:
                sess_q += 1
    return UsageSummary(total_in, total_out, total_cost, total_q,
                        sess_in, sess_out, sess_cost, sess_q)
```

NOTE: `summarize` is called with keyword `session_start=` in tests — keep the keyword-compatible signature (`def summarize(records, *, session_start="")` but tests call `summarize(records, session_start=...)` positionally-compatible; keep as written).

- [ ] **Step 4: Run to verify pass**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_usage_stats.py -v`
Expected: 10 PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/usage_stats.py Dev/kb_chatbot/tests/test_usage_stats.py
git commit -m "feat(v2.4): add usage_stats aggregation module"
```

---

## Task 6: Sonnet Default + Settings Migration

**Files:**
- Modify: `Dev/kb_chatbot/config.py`, `Dev/kb_chatbot/settings.py`
- Test: `Dev/kb_chatbot/tests/test_settings.py` (extend)

- [ ] **Step 1: Write failing tests**

Append to `Dev/kb_chatbot/tests/test_settings.py` (read the file first; reuse its imports/patterns):

```python
def test_default_model_is_sonnet():
    from Dev.kb_chatbot import config
    assert config.DEFAULT_MODEL == "claude-sonnet-4-6"


def test_settings_has_model_explicitly_set_field():
    from Dev.kb_chatbot.settings import Settings
    assert "model_explicitly_set" in Settings.__dataclass_fields__


def test_migrate_upgrades_implicit_haiku():
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import Settings, migrate_default_model
    s = Settings(library_path=config.LIBRARY_DEFAULT,
                 default_model="claude-haiku-4-5-20251001",
                 confidence_floor=config.CONFIDENCE_FLOOR,
                 model_explicitly_set=False)
    assert migrate_default_model(s) is True
    assert s.default_model == "claude-sonnet-4-6"


def test_migrate_keeps_explicit_haiku():
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import Settings, migrate_default_model
    s = Settings(library_path=config.LIBRARY_DEFAULT,
                 default_model="claude-haiku-4-5-20251001",
                 confidence_floor=config.CONFIDENCE_FLOOR,
                 model_explicitly_set=True)
    assert migrate_default_model(s) is False
    assert s.default_model == "claude-haiku-4-5-20251001"


def test_migrate_noop_for_sonnet():
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import Settings, migrate_default_model
    s = Settings(library_path=config.LIBRARY_DEFAULT,
                 default_model="claude-sonnet-4-6",
                 confidence_floor=config.CONFIDENCE_FLOOR,
                 model_explicitly_set=False)
    assert migrate_default_model(s) is False


def test_model_explicitly_set_round_trips():
    import tempfile
    from pathlib import Path
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.settings import Settings, save_settings, load_settings
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "settings.json"
        s = Settings(library_path=config.LIBRARY_DEFAULT,
                     default_model="claude-haiku-4-5-20251001",
                     confidence_floor=config.CONFIDENCE_FLOOR,
                     model_explicitly_set=True)
        save_settings(s, p)
        assert load_settings(p).model_explicitly_set is True
```

- [ ] **Step 2: Run to verify failure**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_settings.py -v`
Expected: failures on the new tests.

- [ ] **Step 3: Implement**

In `Dev/kb_chatbot/config.py`:

```python
DEFAULT_MODEL  = "claude-sonnet-4-6"
```

In `Dev/kb_chatbot/settings.py`:
- Add to `Settings`: `model_explicitly_set: bool = False`
- In `load_settings`'s returned Settings add: `model_explicitly_set=bool(data.get("model_explicitly_set", False))`
- Add module constant and function:

```python
_OLD_HAIKU_DEFAULT = "claude-haiku-4-5-20251001"


def migrate_default_model(settings: Settings) -> bool:
    """One-time upgrade: implicit Haiku default → current (Sonnet) default.
    Returns True if the model was changed (caller announces + persists)."""
    if settings.model_explicitly_set:
        return False
    if settings.default_model != _OLD_HAIKU_DEFAULT:
        return False
    settings.default_model = config.DEFAULT_MODEL
    return True
```

- [ ] **Step 4: Run tests**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_settings.py Dev/kb_chatbot/tests/test_learn_mode.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/settings.py Dev/kb_chatbot/tests/test_settings.py
git commit -m "feat(v2.4): default model Sonnet with one-time settings migration"
```

---

## Task 7: GUI — ThinkingIndicator + Wiring

**Files:**
- Modify: `Dev/kb_chatbot/gui.py`

No Qt unit tests; verify via import + manual run. Surgical edits only.

- [ ] **Step 1: Add the widget**

In `gui.py`, add `import random` to the stdlib imports and `QTimer` to the QtCore import. Add after the module constants:

```python
THINKING_WORDS = [
    "Pondering", "Rummaging the KB", "Connecting dots", "Cross-referencing",
    "Consulting the archives", "Reticulating splines", "Reading the manuals",
    "Chasing citations", "Untangling deals", "Asking the librarian",
    "Double-checking sources", "Brewing an answer",
]
INIT_WORDS = ["Waking up the librarian", "Stretching the neural nets", "Dusting off the archives"]
REPHRASE_TEXT = "Rephrasing your question for a better search"
```

Add the widget class after `InitWorker`:

```python
class ThinkingIndicator(QLabel):
    """Claude-style animated status: '✦ <word>…' with cycling words and pulsing dots."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("color:#7e57c2; font-style:italic; padding:2px 8px;")
        self.setVisible(False)
        self._words: list[str] = []
        self._word_idx = 0
        self._dots = 1
        self._pinned: Optional[str] = None
        self._word_timer = QTimer(self)
        self._word_timer.setInterval(2500)
        self._word_timer.timeout.connect(self._next_word)
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(400)
        self._dot_timer.timeout.connect(self._pulse)

    def start(self, words: list[str]):
        self._words = list(words)
        random.shuffle(self._words)
        self._word_idx = 0
        self._dots = 1
        self._pinned = None
        self._render()
        self.setVisible(True)
        self._word_timer.start()
        self._dot_timer.start()

    def pin(self, text: str):
        """Hold one status (e.g. the rewrite stage) instead of cycling."""
        self._pinned = text
        self._render()

    def stop(self):
        self._word_timer.stop()
        self._dot_timer.stop()
        self.setVisible(False)

    def _next_word(self):
        if self._pinned is None and self._words:
            self._word_idx = (self._word_idx + 1) % len(self._words)
            self._render()

    def _pulse(self):
        self._dots = self._dots % 3 + 1
        self._render()

    def _render(self):
        word = self._pinned if self._pinned is not None else (
            self._words[self._word_idx] if self._words else "Thinking")
        self.setText(f"✦ {word}{'.' * self._dots}")
```

- [ ] **Step 2: Place it in the layout**

In `_build_ui`, directly after `outer.addWidget(self.chat_view, stretch=1)`:

```python
        self._thinking = ThinkingIndicator()
        outer.addWidget(self._thinking)
```

And a second instance for init, added to the status bar in `__init__` right before `self._start_init_worker()` (after `_build_ui()`):

```python
        self._init_thinking = ThinkingIndicator()
        self.statusBar().addWidget(self._init_thinking)
        self._init_thinking.start(INIT_WORDS)
        self.input.setPlaceholderText("Getting ready — one moment…")
```

Note `__init__` already calls `self.statusBar().showMessage("⟳ Initialising — please wait…")` — REMOVE that line (the indicator replaces it).

- [ ] **Step 3: Wire init transitions**

In `_start_init_worker`, change the status connection so SDK warm-up pins the indicator:

```python
        self._init_worker.status.connect(self._on_init_status)
```

Add:

```python
    @Slot(str)
    def _on_init_status(self, msg: str):
        if "Claude" in msg:
            self._init_thinking.pin("Warming up Claude")
```

In `_on_init_ready`, before enabling chat:

```python
        self._init_thinking.stop()
        self.statusBar().removeWidget(self._init_thinking)
        self.input.setPlaceholderText(
            "Ask a question about the Contoso KB… (drag & drop files or Ctrl+V to attach)")
```

In `_on_init_failed`, also `self._init_thinking.stop()`.

- [ ] **Step 4: Wire per-question animation + rewrite progress**

`WorkerSignals` gains `progress = Signal(str)`.

In `_send`, after creating the worker and connecting signals, add:

```python
        self.worker.signals.progress.connect(self._on_turn_progress)
        deps.on_progress = self.worker.signals.progress.emit
        self._thinking.start(THINKING_WORDS)
```

(Set `deps.on_progress` AFTER constructing the worker; `Deps` is a plain dataclass so attribute assignment works. Construct `deps` first as today, then worker, then assign.)

Add the slot:

```python
    @Slot(str)
    def _on_turn_progress(self, stage: str):
        if stage == "rephrase":
            self._thinking.pin(REPHRASE_TEXT)
```

In `_on_turn_done` and `_on_turn_failed`, first line: `self._thinking.stop()`.

Also wire the rewriter into Deps in `_send`:

```python
        from Dev.kb_chatbot.chat.query_rewriter import rewrite_query
        deps = Deps(retriever=self._retriever, llm=llm, usage_logger=_append_usage,
                    attachments=attachments, rewriter=rewrite_query)
```

- [ ] **Step 5: Verify**

```
& "scraper\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, '.'); from Dev.kb_chatbot import gui; print('import OK')"
& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/ -q
```
Expected: import OK; full suite PASS.

- [ ] **Step 6: Commit**

```
git add Dev/kb_chatbot/gui.py
git commit -m "feat(v2.4): ThinkingIndicator animation for queries and startup; wire rewriter"
```

---

## Task 8: GUI — Migration Notice + Token Usage Dialog

**Files:**
- Modify: `Dev/kb_chatbot/gui.py`
- Test: `Dev/kb_chatbot/tests/test_usage_stats.py` (extend with one source-inspection test)

- [ ] **Step 1: Migration notice**

In `MainWindow.__init__`, right after `self.settings = settings_mod.load_settings()`:

```python
        self._model_migrated = settings_mod.migrate_default_model(self.settings)
        if self._model_migrated:
            settings_mod.save_settings(self.settings)
```

In `_on_init_ready`, after the "Ready." system message:

```python
        if self._model_migrated:
            self._append("system",
                "Default model upgraded to Sonnet for better accuracy — "
                "change it back anytime in the dropdown.", "#1b5e20", "SYSTEM:")
            self._model_migrated = False
```

In `SettingsDialog.values()`, add `model_explicitly_set=True,` to the constructed `Settings` (the user explicitly saved a model choice).

Also record session start in `__init__` (used by the dialog):

```python
        self._session_start_ts = datetime.now().isoformat()
```

- [ ] **Step 2: Token usage dialog**

Add `QTableWidget, QTableWidgetItem` to the QtWidgets import. Add after `SettingsDialog`:

```python
class TokenUsageDialog(QDialog):
    """Read-only token usage + API-equivalent cost breakdown from usage.jsonl."""

    _MODEL_DISPLAY = {
        "claude-haiku-4-5-20251001": "Haiku",
        "claude-sonnet-4-6": "Sonnet",
    }

    def __init__(self, parent, session_start: str):
        super().__init__(parent)
        from Dev.kb_chatbot import usage_stats
        self.setWindowTitle("Token Usage")
        self.resize(640, 480)
        layout = QVBoxLayout(self)

        records = usage_stats.load_usage(config.USAGE_FILE)
        s = usage_stats.summarize(records, session_start=session_start)

        def fmt(n: int) -> str:
            return f"{n:,}"

        avg_in = s.total_in // s.total_queries if s.total_queries else 0
        avg_out = s.total_out // s.total_queries if s.total_queries else 0
        avg_cost = s.total_cost / s.total_queries if s.total_queries else 0.0
        summary = QLabel(
            f"<b>All time:</b> {fmt(s.total_in)} in · {fmt(s.total_out)} out · ≈ ${s.total_cost:.2f}<br>"
            f"<b>This session:</b> {fmt(s.session_in)} in · {fmt(s.session_out)} out · ≈ ${s.session_cost:.4f}<br>"
            f"<b>Per query avg:</b> {fmt(avg_in)} in · {fmt(avg_out)} out · ≈ ${avg_cost:.4f}<br>"
            f"<b>Queries:</b> {s.total_queries} all-time · {s.session_queries} this session"
        )
        layout.addWidget(summary)

        table = QTableWidget()
        table.setColumnCount(6)
        table.setHorizontalHeaderLabels(["Time", "Kind", "Model", "In", "Out", "Cost"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        rows = list(reversed(records))  # newest first
        table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            ts = (r.get("ts") or "")[11:19]  # HH:MM:SS
            model = self._MODEL_DISPLAY.get(r.get("model") or "", r.get("model") or "—")
            cost = usage_stats.cost_for(r)
            for col, val in enumerate([ts, r.get("kind", ""), model,
                                       fmt(r.get("tokens_in", 0) or 0),
                                       fmt(r.get("tokens_out", 0) or 0),
                                       f"${cost:.4f}"]):
                table.setItem(i, col, QTableWidgetItem(str(val)))
        table.resizeColumnsToContents()
        layout.addWidget(table, stretch=1)

        footer = QLabel(
            "Rates: Haiku $1/$5 · Sonnet $3/$15 per MTok (API-equivalent) — "
            "Anthropic published pricing, June 2026. Edit config.COST_TABLE if rates change."
        )
        footer.setStyleSheet("color:#777; font-size:9pt;")
        layout.addWidget(footer)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.clicked.connect(self.accept)
        layout.addWidget(bb)
```

- [ ] **Step 3: Button in SettingsDialog**

In `SettingsDialog.__init__`, before the `QDialogButtonBox` row:

```python
        self.usage_btn = QPushButton("View Token Usage…")
        self.usage_btn.clicked.connect(self._open_usage)
        form.addRow(self.usage_btn)
```

Add the method (the parent MainWindow carries the session start):

```python
    def _open_usage(self):
        session_start = getattr(self.parent(), "_session_start_ts", "")
        TokenUsageDialog(self, session_start).exec()
```

- [ ] **Step 4: Regression test**

Append to `Dev/kb_chatbot/tests/test_usage_stats.py`:

```python
def test_gui_wires_usage_dialog():
    """SettingsDialog must expose the usage button; TokenUsageDialog must exist."""
    import inspect
    from Dev.kb_chatbot import gui
    assert hasattr(gui, "TokenUsageDialog")
    src = inspect.getsource(gui.SettingsDialog.__init__)
    assert "View Token Usage" in src
```

- [ ] **Step 5: Verify**

```
& "scraper\venv\Scripts\python.exe" -c "import sys; sys.path.insert(0, '.'); from Dev.kb_chatbot import gui; print('import OK')"
& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/ -q
```
Expected: import OK; full suite PASS.

- [ ] **Step 6: Commit**

```
git add Dev/kb_chatbot/gui.py Dev/kb_chatbot/tests/test_usage_stats.py
git commit -m "feat(v2.4): token usage dialog, settings button, Sonnet migration notice"
```

---

## Task 9: Final Integration

- [ ] **Step 1: Full suite**

Run: `& "scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/ -q`
Expected: all PASS (~130 tests, ~2.5 min).

- [ ] **Step 2: Manual walkthrough checklist (user performs after exe rebuild)**

1. Launch → status bar shows `✦ Waking up the librarian…` animating; placeholder "Getting ready"
2. Ready → one-time "Default model upgraded to Sonnet" notice; model dropdown shows Sonnet
3. Ask a question → `✦ Pondering…` animation cycles under the chat, vanishes on answer
4. Ask "How do I post a deal?" (no product) → clarification → reply "TradeDesk" → bot answers the ORIGINAL question for TradeDesk (the v2.3 failure case)
5. Ask a follow-up "how do I reverse it?" → relevant answer (fusion)
6. Ask something contextual that abstains → indicator switches to `✦ Rephrasing your question…` → either an answer or honest abstain with suggestions
7. Settings → "View Token Usage…" → summary + table render; rewrite rows visible; costs plausible
8. Clear chat → animation states reset cleanly

- [ ] **Step 3: Commit any stragglers; do not merge** (finishing-a-development-branch handles that)
