# KB Chatbot v2.3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add multi-turn conversation, clickable source links, instant startup, file/screenshot uploads, Learn Mode, and article suggestions to the v2.2 KB Chatbot.

**Architecture:** Six additive changes layered on top of the existing v2.2 retrieval core (ChromaDB + SentenceTransformer + CrossEncoder + ClaudeCodeProvider). The ingest pipeline, chunker, and scraper are untouched. GUI changes are the most substantial — `gui.py` gains `InitWorker`, an attachment bar, and Learn Mode UI.

**Tech Stack:** PySide6, ChromaDB, sentence-transformers, claude-agent-sdk, Python 3.10+

**Working directory for all tasks:** `Dev/kb_chatbot/` inside the Knowledge Base project root.

---

## File Map

| File | Status | Changes |
|------|--------|---------|
| `chat/session.py` | Modify | Add `last_rerank_score` to `Session`; add `attachments` to `Turn` |
| `citations.py` | Modify | New regex `[Title](url)`; add `url` field to `Citation` |
| `prompt.py` | Modify | Context block includes URL; updated system prompt; add `format_suggestions()`; `build_messages()` accepts attachments |
| `llm/claude_code_provider.py` | Modify | `_query_persistent()` accepts `messages: list[dict]`; remove `_latest_user_text` |
| `chat/orchestrator.py` | Modify | Topic-drift check; suggestion engine; short-query clarification |
| `retriever.py` | Modify | Add `suggest()` method |
| `settings.py` | Modify | Add `learn_mode_hash`; add `check_learn_password()` |
| `chat/learn_writer.py` | **New** | Write learned entries to `library/learned/` |
| `gui.py` | Modify | `QTextBrowser`; `InitWorker`; attachment bar; Learn Mode UI |
| `tests/test_multi_turn.py` | **New** | Multi-turn + topic-drift tests |
| `tests/test_citations_url.py` | **New** | Citation URL tests |
| `tests/test_suggestions.py` | **New** | Suggestion engine tests |
| `tests/test_learn_mode.py` | **New** | Password hash + learn_writer tests |
| `tests/test_attachments.py` | **New** | Attachment building tests |

---

## Task 1: Data Model — Session and Turn

**Files:**
- Modify: `chat/session.py`
- Test: `tests/test_multi_turn.py`

- [ ] **Step 1: Write the failing test**

Create `Dev/kb_chatbot/tests/test_multi_turn.py`:

```python
from Dev.kb_chatbot.chat.session import Session, Turn


def test_session_has_last_rerank_score():
    s = Session.new()
    assert hasattr(s, "last_rerank_score")
    assert s.last_rerank_score == 0.0


def test_session_last_rerank_score_updates():
    s = Session.new()
    s.last_rerank_score = 0.75
    assert s.last_rerank_score == 0.75


def test_turn_has_attachments():
    t = Turn(role="user", content="hello")
    assert hasattr(t, "attachments")
    assert t.attachments == []


def test_turn_attachments_stored():
    t = Turn(role="user", content="hello", attachments=["screenshot.png"])
    assert t.attachments == ["screenshot.png"]
```

- [ ] **Step 2: Run test to confirm it fails**

```
cd "C:\Users\AbdulRaqeebKhatri\OneDrive\Documents\Knowledge Base"
python -m pytest Dev/kb_chatbot/tests/test_multi_turn.py -v
```

Expected: 4 failures — `Session` has no `last_rerank_score`, `Turn` has no `attachments`.

- [ ] **Step 3: Implement**

In `Dev/kb_chatbot/chat/session.py`, make these exact changes:

```python
@dataclass
class Turn:
    role: str
    content: str
    kind: str = "answer"
    citations: list[dict] = field(default_factory=list)
    retrieved_ids: list[str] = field(default_factory=list)
    attachments: list[str] = field(default_factory=list)   # ADD THIS LINE
    model: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    ts: str = field(default_factory=lambda: datetime.now().isoformat())
```

```python
@dataclass
class Session:
    id: str
    turns: list[dict] = field(default_factory=list)
    last_rerank_score: float = 0.0                          # ADD THIS LINE
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest Dev/kb_chatbot/tests/test_multi_turn.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/chat/session.py Dev/kb_chatbot/tests/test_multi_turn.py
git commit -m "feat(v2.3): add last_rerank_score to Session and attachments to Turn"
```

---

## Task 2: Citations — URL Enrichment

**Files:**
- Modify: `citations.py`
- Test: `tests/test_citations_url.py`

- [ ] **Step 1: Write the failing test**

Create `Dev/kb_chatbot/tests/test_citations_url.py`:

```python
from Dev.kb_chatbot.citations import validate, Citation
from Dev.kb_chatbot.chunker import Chunk


def _make_chunk(title, url, product="tradedesk", category="dealing"):
    return Chunk(
        id="test-1",
        text="Some content",
        metadata={"product": product, "category": category, "title": title, "url": url},
    )


def test_citation_has_url_field():
    c = Citation(raw="[Title](http://example.com)", title="Title", url="http://example.com")
    assert c.url == "http://example.com"


def test_validate_populates_url_on_verified_citation():
    chunk = _make_chunk("Book a Retail Deal", "https://help.contoso.example/display/DEAL")
    answer = "Do this step. [Book a Retail Deal](https://help.contoso.example/display/DEAL)"
    result = validate(answer, [chunk])
    assert len(result.verified) == 1
    assert result.verified[0].url == "https://help.contoso.example/display/DEAL"


def test_validate_marks_unknown_url_as_unverified():
    chunk = _make_chunk("Book a Retail Deal", "https://help.contoso.example/display/DEAL")
    answer = "See this. [Made Up Article](https://help.contoso.example/display/FAKE)"
    result = validate(answer, [chunk])
    assert len(result.unverified) == 1
    assert "[unverified]" in result.stripped_text


def test_validate_verified_citation_not_replaced():
    chunk = _make_chunk("Book a Retail Deal", "https://help.contoso.example/display/DEAL")
    answer = "Do this. [Book a Retail Deal](https://help.contoso.example/display/DEAL)"
    result = validate(answer, [chunk])
    assert "[unverified]" not in result.stripped_text
    assert "Book a Retail Deal" in result.stripped_text
```

- [ ] **Step 2: Run test to confirm it fails**

```
python -m pytest Dev/kb_chatbot/tests/test_citations_url.py -v
```

Expected: failures — `Citation` has no `url`, `validate` doesn't match new format.

- [ ] **Step 3: Implement**

Replace `Dev/kb_chatbot/citations.py` entirely:

```python
"""V2.3 citations: parse + validate [Title](url) citation form."""
from __future__ import annotations
import logging
import re
from dataclasses import dataclass, field
from typing import List

from Dev.kb_chatbot.chunker import Chunk

log = logging.getLogger("kb_chatbot.citations")

# Matches [Title](https://...)
_CITE_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")


@dataclass
class Citation:
    raw: str
    title: str
    url: str


@dataclass
class ValidationResult:
    all_verified: bool
    stripped_text: str
    verified: list[Citation] = field(default_factory=list)
    unverified: list[Citation] = field(default_factory=list)


def parse_citations(text: str) -> List[Citation]:
    out = []
    for m in _CITE_RE.finditer(text):
        out.append(Citation(
            raw=m.group(0),
            title=m.group(1).strip(),
            url=m.group(2).strip(),
        ))
    return out


def _matches(cite: Citation, chunk: Chunk) -> bool:
    return cite.url == chunk.metadata.get("url", "")


def validate(answer: str, retrieved: list[Chunk]) -> ValidationResult:
    cites = parse_citations(answer)
    verified, unverified = [], []
    for c in cites:
        if any(_matches(c, ch) for ch in retrieved):
            verified.append(c)
        else:
            unverified.append(c)
            log.warning("Unverified citation: %s", c.raw)

    stripped = answer
    for u in unverified:
        stripped = stripped.replace(u.raw, "[unverified]")

    return ValidationResult(
        all_verified=len(unverified) == 0,
        stripped_text=stripped,
        verified=verified,
        unverified=unverified,
    )
```

- [ ] **Step 4: Run tests**

```
python -m pytest Dev/kb_chatbot/tests/test_citations_url.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/citations.py Dev/kb_chatbot/tests/test_citations_url.py
git commit -m "feat(v2.3): update citations to [Title](url) format with URL validation"
```

---

## Task 3: Prompt — Context Block, System Prompt, Suggestions, Attachments

**Files:**
- Modify: `prompt.py`
- Test: `tests/test_suggestions.py` (partial — suggestion formatter)

- [ ] **Step 1: Write failing tests for new prompt functions**

Add to `Dev/kb_chatbot/tests/test_suggestions.py` (create new file):

```python
from Dev.kb_chatbot.prompt import format_suggestions, build_messages
from Dev.kb_chatbot.chunker import Chunk


def _chunk(title, url, product="tradedesk", category="dealing"):
    return Chunk(
        id="x", text="content",
        metadata={"product": product, "category": category, "title": title, "url": url},
    )


def test_format_suggestions_produces_markdown_links():
    chunks = [
        _chunk("Book a Retail Deal", "https://help.contoso.example/deal"),
        _chunk("Deal Types", "https://help.contoso.example/types"),
    ]
    result = format_suggestions(chunks)
    assert "[Book a Retail Deal](https://help.contoso.example/deal)" in result
    assert "[Deal Types](https://help.contoso.example/types)" in result


def test_format_suggestions_empty_returns_empty():
    assert format_suggestions([]) == ""


def test_build_messages_includes_url_in_context():
    chunk = _chunk("Book a Retail Deal", "https://help.contoso.example/deal")
    msgs = build_messages(context_chunks=[chunk], history=[], user_msg="How?")
    last_content = msgs[-1]["content"]
    assert "https://help.contoso.example/deal" in last_content


def test_build_messages_text_attachment_prepended():
    from Dev.kb_chatbot.prompt import Attachment
    chunk = _chunk("Book a Retail Deal", "https://help.contoso.example/deal")
    att = Attachment(filename="notes.txt", media_type="text/plain",
                     data=b"some log content", is_image=False)
    msgs = build_messages(context_chunks=[chunk], history=[], user_msg="Why?",
                          attachments=[att])
    last_content = msgs[-1]["content"]
    assert "[Attached: notes.txt]" in last_content
    assert "some log content" in last_content


def test_build_messages_image_attachment_creates_list_content():
    from Dev.kb_chatbot.prompt import Attachment
    chunk = _chunk("Book a Retail Deal", "https://help.contoso.example/deal")
    att = Attachment(filename="screen.png", media_type="image/png",
                     data=b"\x89PNG", is_image=True)
    msgs = build_messages(context_chunks=[chunk], history=[], user_msg="What is this?",
                          attachments=[att])
    last_content = msgs[-1]["content"]
    assert isinstance(last_content, list)
    types = [b["type"] for b in last_content]
    assert "image" in types
    assert "text" in types
```

- [ ] **Step 2: Run to confirm failures**

```
python -m pytest Dev/kb_chatbot/tests/test_suggestions.py -v
```

Expected: failures — `format_suggestions`, `Attachment` not defined yet.

- [ ] **Step 3: Implement**

Replace `Dev/kb_chatbot/prompt.py` entirely:

```python
"""V2.3 prompt: locked system prompt, context formatter, suggestion formatter, message builder."""
from __future__ import annotations
import base64
from dataclasses import dataclass
from typing import Optional

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import Chunk


SYSTEM_PROMPT = """You are the Contoso Knowledge Base Assistant. You answer questions about Contoso KB articles — release notes, how-to guides, API references, and product documentation for TradeDesk, Web2, Web4, SalesHub, and the API.

Hard rules — no exceptions:
1. You may only use facts from the CONTEXT block. You have no other knowledge of Contoso products. Do not use general knowledge, intuition, or assumptions.
2. If the answer is not in the context, reply: "I don't have enough information in the knowledge base to answer this confidently." — never invent facts.
3. Every factual claim must end with a Markdown link citation using the exact URL from the CONTEXT block: [Article Title](url). Never invent a URL.
4. If the user's intent is ambiguous (could refer to multiple products or topics), do not answer. Ask exactly one clarifying question.
5. If the user attaches an image or file, use it as additional context alongside the KB articles. Do not describe the image unless asked.
6. Format the answer as: one-sentence direct answer first; then bullet list of relevant steps (each with citation link); then a "Searched:" footnote naming the product(s) considered.

Do not editorialise. Do not apologise. Do not speculate. Do not summarise articles that were not retrieved."""


@dataclass
class Attachment:
    filename: str
    media_type: str   # e.g. "image/png", "text/plain"
    data: bytes
    is_image: bool


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def _cite_handle(meta: dict) -> str:
    product = config.PRODUCT_DISPLAY.get(meta.get("product", ""), meta.get("product", ""))
    category = meta.get("category", "") or "general"
    title = meta.get("title", "")
    url = meta.get("url", "")
    if url:
        return f"[{product} · {category} · {title}]({url})"
    return f"[{product} · {category} · {title}]"


def format_context(chunks: list[Chunk]) -> str:
    if not chunks:
        return "CONTEXT (the only facts you may use):\n\n(no relevant articles found)\n"
    lines = ["CONTEXT (the only facts you may use):", ""]
    for i, c in enumerate(chunks, 1):
        cite = _cite_handle(c.metadata)
        lines.append(f"{i}. {cite}")
        lines.append(f"   {c.text}")
        lines.append("")
    return "\n".join(lines)


def format_suggestions(chunks: list[Chunk]) -> str:
    if not chunks:
        return ""
    seen_titles: set[str] = set()
    lines = []
    for c in chunks:
        title = c.metadata.get("title", "")
        url = c.metadata.get("url", "")
        product = config.PRODUCT_DISPLAY.get(c.metadata.get("product", ""), "")
        category = c.metadata.get("category", "")
        if title in seen_titles or not url:
            continue
        seen_titles.add(title)
        lines.append(f"• [{title}]({url})  — {product} · {category}")
    return "\n".join(lines)


def _build_text_block(context_chunks: list[Chunk], user_msg: str,
                      text_attachments: list[Attachment]) -> str:
    parts = [format_context(context_chunks)]
    for att in text_attachments:
        try:
            text = att.data.decode("utf-8", errors="replace")
        except Exception:
            text = "(could not decode file)"
        max_chars = 20_000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[truncated]"
        parts.append(f"[Attached: {att.filename}]\n```\n{text}\n```")
    parts.append(f"USER QUESTION:\n{user_msg}")
    return "\n\n".join(parts)


def build_messages(
    *,
    context_chunks: list[Chunk],
    history: list[dict],
    user_msg: str,
    attachments: Optional[list[Attachment]] = None,
) -> list[dict]:
    attachments = attachments or []
    images = [a for a in attachments if a.is_image]
    texts = [a for a in attachments if not a.is_image]

    text_block = _build_text_block(context_chunks, user_msg, texts)

    if images:
        content: list[dict] = []
        for img in images:
            b64 = base64.b64encode(img.data).decode()
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": img.media_type, "data": b64},
            })
        content.append({"type": "text", "text": text_block})
        user_turn: dict = {"role": "user", "content": content}
    else:
        user_turn = {"role": "user", "content": text_block}

    return [*history, user_turn]
```

- [ ] **Step 4: Run tests**

```
python -m pytest Dev/kb_chatbot/tests/test_suggestions.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/prompt.py Dev/kb_chatbot/tests/test_suggestions.py
git commit -m "feat(v2.3): update prompt with URL citations, suggestion formatter, attachment support"
```

---

## Task 4: Multi-Turn — Fix ClaudeCodeProvider

**Files:**
- Modify: `llm/claude_code_provider.py`
- Test: `tests/test_multi_turn.py` (extend)

- [ ] **Step 1: Add test**

Append to `Dev/kb_chatbot/tests/test_multi_turn.py`:

```python
from Dev.kb_chatbot.llm.claude_code_provider import _build_user_prompt


def test_build_user_prompt_includes_all_turns():
    messages = [
        {"role": "user", "content": "How do I book a deal?"},
        {"role": "assistant", "content": "Navigate to Dealing > New Deal."},
        {"role": "user", "content": "CONTEXT: ...\nUSER QUESTION:\nHow do I reverse that?"},
    ]
    result = _build_user_prompt(messages)
    assert "How do I book a deal?" in result
    assert "Navigate to Dealing" in result
    assert "How do I reverse that?" in result


def test_build_user_prompt_handles_list_content():
    messages = [
        {"role": "user", "content": [
            {"type": "image", "source": {}},
            {"type": "text", "text": "What is this?"},
        ]},
    ]
    result = _build_user_prompt(messages)
    assert "What is this?" in result
```

- [ ] **Step 2: Run to confirm test for `_build_user_prompt` list content fails**

```
python -m pytest Dev/kb_chatbot/tests/test_multi_turn.py::test_build_user_prompt_handles_list_content -v
```

Expected: FAIL — current `_build_user_prompt` doesn't handle list content.

- [ ] **Step 3: Update `_build_user_prompt` and `chat()` in `llm/claude_code_provider.py`**

Replace `_build_user_prompt` and `_latest_user_text` and update `chat()` and `_query_persistent()`:

```python
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
```

In the `chat()` method, replace:
```python
    def chat(self, *, messages, model, system_prompt, max_tokens=1024) -> LLMResponse:
        started = time.time()
        prompt = _latest_user_text(messages)
        backend = ClaudeCodeProvider._backend
        if backend is None:
            raise RuntimeError("ClaudeCodeProvider backend not initialised")
        text, in_tok, out_tok = backend.submit(
            self._query_persistent(prompt, model, system_prompt)
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
```

with:

```python
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
```

Replace `_query_persistent` signature and its prompt usage:

```python
    async def _query_persistent(self, messages: list[dict], model: str, system_prompt: str) -> tuple[str, int, int]:
        await self._ensure_client(system_prompt, model)
        cls = ClaudeCodeProvider
        prompt = _build_user_prompt(messages)
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
```

Also delete the `_latest_user_text` function (it's no longer used).

- [ ] **Step 4: Run all multi-turn tests**

```
python -m pytest Dev/kb_chatbot/tests/test_multi_turn.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/llm/claude_code_provider.py Dev/kb_chatbot/tests/test_multi_turn.py
git commit -m "feat(v2.3): pass full conversation history to Claude SDK for multi-turn support"
```

---

## Task 5: Multi-Turn — Topic Drift in Orchestrator

**Files:**
- Modify: `chat/orchestrator.py`
- Test: `tests/test_multi_turn.py` (extend)

- [ ] **Step 1: Add tests**

Append to `Dev/kb_chatbot/tests/test_multi_turn.py`:

```python
from Dev.kb_chatbot.chat.orchestrator import _is_topic_drift


def test_no_drift_when_previous_score_low():
    # If previous score was low, no drift (was already uncertain)
    assert _is_topic_drift(previous=0.2, current=0.1) is False


def test_no_drift_when_current_score_adequate():
    assert _is_topic_drift(previous=0.8, current=0.5) is False


def test_drift_detected_when_score_drops_sharply():
    # Previous high confidence, current very low = topic change
    assert _is_topic_drift(previous=0.7, current=0.15) is True


def test_no_drift_at_boundary():
    assert _is_topic_drift(previous=0.5, current=0.20) is False  # exactly at boundary
```

- [ ] **Step 2: Run to confirm failures**

```
python -m pytest Dev/kb_chatbot/tests/test_multi_turn.py::test_drift_detected_when_score_drops_sharply -v
```

Expected: FAIL — `_is_topic_drift` not defined.

- [ ] **Step 3: Add `_is_topic_drift` and integrate into `handle_turn`**

In `Dev/kb_chatbot/chat/orchestrator.py`, add after the imports:

```python
_DRIFT_PREVIOUS_FLOOR = 0.50   # previous turn must have been confident
_DRIFT_CURRENT_CEILING = 0.20  # current turn must be very low

DRIFT_NOTE = "\n\n[TOPIC SHIFT: The user has changed topics. Treat this as a fresh question. Do not reference prior context.]"


def _is_topic_drift(previous: float, current: float) -> bool:
    return previous >= _DRIFT_PREVIOUS_FLOOR and current < _DRIFT_CURRENT_CEILING
```

Inside `handle_turn`, after `result = deps.retriever.retrieve(user_msg, filters)`, add:

```python
    # Topic-drift: inject note if confidence dropped sharply from previous turn
    drift_note = ""
    if _is_topic_drift(session.last_rerank_score, result.rerank_top_score):
        drift_note = DRIFT_NOTE
    session.last_rerank_score = result.rerank_top_score
```

Then in the LLM call block, change `user_msg=user_msg` to `user_msg=user_msg + drift_note`:

```python
            messages = build_messages(
                context_chunks=result.chunks,
                history=session.history_for_llm(config.MAX_HISTORY_TURNS),
                user_msg=user_msg + drift_note,
            )
```

- [ ] **Step 4: Run tests**

```
python -m pytest Dev/kb_chatbot/tests/test_multi_turn.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_multi_turn.py
git commit -m "feat(v2.3): add topic-drift detection to orchestrator"
```

---

## Task 6: Retriever — `suggest()` Method

**Files:**
- Modify: `retriever.py`
- Test: `tests/test_suggestions.py` (extend)

- [ ] **Step 1: Add test**

Append to `Dev/kb_chatbot/tests/test_suggestions.py`:

```python
from unittest.mock import MagicMock, patch
from Dev.kb_chatbot.retriever import Retriever, Filters
from Dev.kb_chatbot.chunker import Chunk
from pathlib import Path


def _make_retriever_with_mock_chroma(chunks):
    """Build a Retriever with mocked ChromaDB and real embedding stub."""
    with patch("Dev.kb_chatbot.retriever.chromadb.PersistentClient"), \
         patch("Dev.kb_chatbot.retriever.SentenceTransformer") as mock_st, \
         patch("Dev.kb_chatbot.retriever.CrossEncoder"):
        mock_st.return_value.encode.return_value = [[0.1] * 384]
        r = Retriever(Path("/fake/chroma"))
        r._embed = lambda text: [0.1] * 384
        r._query_chroma = MagicMock(return_value=chunks)
        return r


def test_suggest_returns_chunks():
    chunks = [
        Chunk(id="a", text="t1", metadata={"title": "A", "url": "https://x.com/a",
              "product": "tradedesk", "category": "dealing"}),
        Chunk(id="b", text="t2", metadata={"title": "B", "url": "https://x.com/b",
              "product": "tradedesk", "category": "dealing"}),
    ]
    r = _make_retriever_with_mock_chroma(chunks)
    results = r.suggest("how to book")
    assert len(results) == 2


def test_suggest_deduplicates_by_title():
    dup_chunk = Chunk(id="a2", text="t1b", metadata={"title": "A", "url": "https://x.com/a",
                      "product": "tradedesk", "category": "dealing"})
    chunk_b = Chunk(id="b", text="t2", metadata={"title": "B", "url": "https://x.com/b",
                    "product": "tradedesk", "category": "dealing"})
    r = _make_retriever_with_mock_chroma([dup_chunk, dup_chunk, chunk_b])
    results = r.suggest("how to book")
    titles = [c.metadata["title"] for c in results]
    assert titles.count("A") == 1
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest Dev/kb_chatbot/tests/test_suggestions.py::test_suggest_returns_chunks -v
```

Expected: FAIL — `Retriever` has no `suggest` method.

- [ ] **Step 3: Add `suggest()` to `retriever.py`**

In `Dev/kb_chatbot/retriever.py`, add this method to the `Retriever` class after `retrieve_quick`:

```python
    def suggest(self, query: str, top_k: int = 5, threshold: float = 0.10) -> list[Chunk]:
        """Low-threshold retrieval for article suggestions when confidence is low.
        Uses vector similarity only (no reranking) to keep latency minimal.
        Returns up to top_k chunks deduplicated by title."""
        query_vec = self._embed(query)
        candidates = self._query_chroma(query_vec, Filters(), top_k * 2)
        seen_titles: set[str] = set()
        results: list[Chunk] = []
        for chunk in candidates:
            title = chunk.metadata.get("title", "")
            if title and title not in seen_titles:
                seen_titles.add(title)
                results.append(chunk)
            if len(results) >= top_k:
                break
        return results
```

- [ ] **Step 4: Run tests**

```
python -m pytest Dev/kb_chatbot/tests/test_suggestions.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/retriever.py Dev/kb_chatbot/tests/test_suggestions.py
git commit -m "feat(v2.3): add suggest() to Retriever for low-confidence article surfacing"
```

---

## Task 7: Orchestrator — Suggestions + Clarification Check

**Files:**
- Modify: `chat/orchestrator.py`
- Test: `tests/test_suggestions.py` (extend)

- [ ] **Step 1: Add tests**

Append to `Dev/kb_chatbot/tests/test_suggestions.py`:

```python
from Dev.kb_chatbot.chat.orchestrator import _is_short_unspecified_query, ABSTAIN_WITH_SUGGESTIONS_TEMPLATE


def test_short_query_detected():
    assert _is_short_unspecified_query("deal") is True
    assert _is_short_unspecified_query("hi") is True


def test_long_query_not_short():
    assert _is_short_unspecified_query("How do I book a retail deal in TradeDesk?") is False


def test_product_named_query_not_unspecified():
    assert _is_short_unspecified_query("tradedesk deal") is False


def test_abstain_template_exists():
    assert "related" in ABSTAIN_WITH_SUGGESTIONS_TEMPLATE.lower()
```

- [ ] **Step 2: Run to confirm failures**

```
python -m pytest Dev/kb_chatbot/tests/test_suggestions.py::test_short_query_detected -v
```

Expected: FAIL.

- [ ] **Step 3: Add to `orchestrator.py`**

Add these constants and helper after the existing `ABSTAIN_MESSAGE`:

```python
ABSTAIN_WITH_SUGGESTIONS_TEMPLATE = """\
I don't have enough information in the knowledge base to answer this confidently.

Here are some articles that might be related — do any of these match what you're looking for?

{suggestions}

If none of these help, try rephrasing your question or use Learn Mode to add the missing information."""

LOW_CONFIDENCE_FOOTER = """\

---
*Not fully certain this covers your question. You might also check:*
{suggestions}"""

SHORT_QUERY_CLARIFICATION = (
    "Could you give me a bit more context? For example, which product are you asking about "
    "(TradeDesk, API, Web2, Web4, or SalesHub) and what you're trying to do?"
)

_SHORT_QUERY_WORD_LIMIT = 4


def _is_short_unspecified_query(text: str) -> bool:
    words = text.strip().split()
    if len(words) >= _SHORT_QUERY_WORD_LIMIT:
        return False
    return not _mentions_product(text)
```

Then update the abstain path in `handle_turn`. Replace the final abstain block:

```python
    # ── Abstain path ─────────────────────────────────────────────────────────
    if _is_short_unspecified_query(user_msg):
        turn = Turn(role="assistant", kind="clarification",
                    content=SHORT_QUERY_CLARIFICATION)
        session.add(turn)
        deps.usage_logger(turn)
        return turn

    suggestions = deps.retriever.suggest(user_msg)
    from Dev.kb_chatbot.prompt import format_suggestions
    suggestion_block = format_suggestions(suggestions)

    if suggestion_block:
        content = ABSTAIN_WITH_SUGGESTIONS_TEMPLATE.format(suggestions=suggestion_block)
    else:
        content = ABSTAIN_MESSAGE

    turn = Turn(role="assistant", kind="abstain", content=content)
    session.add(turn)
    deps.usage_logger(turn)
    return turn
```

Also add low-confidence footer after the successful LLM answer. After `vr = validate_citations(...)` and before creating the final `Turn`, add:

```python
        answer_text = vr.stripped_text
        # Append suggestion footnote for borderline-confidence answers
        LOW_CONFIDENCE_CEILING = 0.45
        if result.rerank_top_score < LOW_CONFIDENCE_CEILING:
            suggestions = deps.retriever.suggest(user_msg)
            from Dev.kb_chatbot.prompt import format_suggestions
            suggestion_block = format_suggestions(suggestions)
            if suggestion_block:
                answer_text += LOW_CONFIDENCE_FOOTER.format(suggestions=suggestion_block)
```

And update the `Turn` creation to use `answer_text`:

```python
        turn = Turn(
            role="assistant",
            content=answer_text,
            kind="answer",
            ...
        )
```

- [ ] **Step 4: Run tests**

```
python -m pytest Dev/kb_chatbot/tests/test_suggestions.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_suggestions.py
git commit -m "feat(v2.3): add suggestion engine and short-query clarification to orchestrator"
```

---

## Task 8: Settings — Learn Mode Password Hash

**Files:**
- Modify: `settings.py`
- Test: `tests/test_learn_mode.py`

- [ ] **Step 1: Write failing tests**

Create `Dev/kb_chatbot/tests/test_learn_mode.py`:

```python
import hashlib
from Dev.kb_chatbot.settings import check_learn_password, Settings, load_settings, save_settings
import tempfile, json
from pathlib import Path


_CORRECT = "YOUR_LEARN_PASSWORD_HERE"
_CORRECT_HASH = hashlib.sha256(_CORRECT.encode()).hexdigest()


def test_check_learn_password_correct():
    assert check_learn_password(_CORRECT, _CORRECT_HASH) is True


def test_check_learn_password_wrong():
    assert check_learn_password("wrongpassword", _CORRECT_HASH) is False


def test_check_learn_password_empty():
    assert check_learn_password("", _CORRECT_HASH) is False


def test_settings_has_learn_mode_hash_field():
    s = Settings.__dataclass_fields__
    assert "learn_mode_hash" in s


def test_settings_saves_and_loads_learn_mode_hash():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "settings.json"
        from Dev.kb_chatbot import config
        s = Settings(
            library_path=config.LIBRARY_DEFAULT,
            default_model=config.DEFAULT_MODEL,
            confidence_floor=config.CONFIDENCE_FLOOR,
            learn_mode_hash=_CORRECT_HASH,
        )
        save_settings(s, path)
        loaded = load_settings(path)
        assert loaded.learn_mode_hash == _CORRECT_HASH
```

- [ ] **Step 2: Run to confirm failures**

```
python -m pytest Dev/kb_chatbot/tests/test_learn_mode.py -v
```

Expected: failures — `check_learn_password` not defined, `Settings` has no `learn_mode_hash`.

- [ ] **Step 3: Implement**

Replace `Dev/kb_chatbot/settings.py`:

```python
"""Persisted settings (JSON). V2.3 adds learn_mode_hash for Learn Mode access control."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from Dev.kb_chatbot import config

# Default password hash: SHA-256 of "YOUR_LEARN_PASSWORD_HERE"
_DEFAULT_LEARN_PASSWORD = "YOUR_LEARN_PASSWORD_HERE"
DEFAULT_LEARN_MODE_HASH = hashlib.sha256(_DEFAULT_LEARN_PASSWORD.encode()).hexdigest()


@dataclass
class Settings:
    library_path: Path
    default_model: str
    confidence_floor: float
    learn_mode_hash: str = DEFAULT_LEARN_MODE_HASH


def check_learn_password(candidate: str, stored_hash: str) -> bool:
    """Compare SHA-256 hash of candidate against stored_hash."""
    if not candidate:
        return False
    return hashlib.sha256(candidate.encode()).hexdigest() == stored_hash


def load_settings(path: Path = config.SETTINGS_FILE) -> Settings:
    defaults = Settings(
        library_path=config.LIBRARY_DEFAULT,
        default_model=config.DEFAULT_MODEL,
        confidence_floor=config.CONFIDENCE_FLOOR,
    )
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    return Settings(
        library_path=Path(data.get("library_path", str(defaults.library_path))),
        default_model=data.get("default_model", defaults.default_model),
        confidence_floor=float(data.get("confidence_floor", defaults.confidence_floor)),
        learn_mode_hash=data.get("learn_mode_hash", DEFAULT_LEARN_MODE_HASH),
    )


def save_settings(settings: Settings, path: Path = config.SETTINGS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**asdict(settings), "library_path": str(settings.library_path)}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests**

```
python -m pytest Dev/kb_chatbot/tests/test_learn_mode.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/settings.py Dev/kb_chatbot/tests/test_learn_mode.py
git commit -m "feat(v2.3): add learn_mode_hash and check_learn_password to settings"
```

---

## Task 9: Learn Writer — New File

**Files:**
- Create: `chat/learn_writer.py`
- Test: `tests/test_learn_mode.py` (extend)

- [ ] **Step 1: Add tests**

Append to `Dev/kb_chatbot/tests/test_learn_mode.py`:

```python
import tempfile, json
from pathlib import Path
from Dev.kb_chatbot.chat.learn_writer import write_learned_entry


def test_write_creates_json_file():
    with tempfile.TemporaryDirectory() as d:
        library_path = Path(d)
        write_learned_entry(
            library_path=library_path,
            product="tradedesk",
            topic="dealing",
            title="How to reverse a posted deal",
            body_md="To reverse: navigate to...",
            url="https://help.contoso.example/display/DEAL",
            original_question="How do I undo a posted deal?",
        )
        learned_dir = library_path / "learned"
        files = list(learned_dir.glob("learned_*.json"))
        assert len(files) == 1


def test_write_json_has_correct_schema():
    with tempfile.TemporaryDirectory() as d:
        library_path = Path(d)
        write_learned_entry(
            library_path=library_path,
            product="api",
            topic="functions",
            title="Using the REST API",
            body_md="Call GET /endpoint...",
            url="",
            original_question="How does the API work?",
        )
        files = list((library_path / "learned").glob("*.json"))
        data = json.loads(files[0].read_text())
        assert data["space_key"] == "learned"
        assert data["product"] == "api"
        assert data["title"] == "Using the REST API"
        assert "learned_at" in data
        assert data["original_question"] == "How does the API work?"


def test_write_stable_filename_for_same_entry():
    with tempfile.TemporaryDirectory() as d:
        library_path = Path(d)
        kwargs = dict(library_path=library_path, product="tradedesk", topic="dealing",
                      title="Same Title", body_md="content", url="", original_question="q")
        write_learned_entry(**kwargs)
        write_learned_entry(**kwargs)
        files = list((library_path / "learned").glob("*.json"))
        assert len(files) == 1  # second write overwrites first (same stable hash)
```

- [ ] **Step 2: Run to confirm failures**

```
python -m pytest Dev/kb_chatbot/tests/test_learn_mode.py::test_write_creates_json_file -v
```

Expected: FAIL — `learn_writer` module not found.

- [ ] **Step 3: Create `chat/learn_writer.py`**

Create `Dev/kb_chatbot/chat/learn_writer.py`:

```python
"""Write user-contributed KB entries to library/learned/ for ingestion."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime
from pathlib import Path


def write_learned_entry(
    *,
    library_path: Path,
    product: str,
    topic: str,
    title: str,
    body_md: str,
    url: str,
    original_question: str,
) -> Path:
    learned_dir = library_path / "learned"
    learned_dir.mkdir(parents=True, exist_ok=True)

    stable_key = hashlib.sha1(f"{product}:{title}".encode()).hexdigest()[:16]
    filename = f"learned_{stable_key}.json"

    entry = {
        "space_key": "learned",
        "space_name": "Learned",
        "product": product,
        "title": title,
        "url": url,
        "body_md": body_md,
        "learned_at": datetime.now().isoformat(timespec="seconds"),
        "contributed_by": "learn_mode",
        "original_question": original_question,
    }

    out_path = learned_dir / filename
    out_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path
```

- [ ] **Step 4: Run tests**

```
python -m pytest Dev/kb_chatbot/tests/test_learn_mode.py -v
```

Expected: all PASSED.

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/chat/learn_writer.py Dev/kb_chatbot/tests/test_learn_mode.py
git commit -m "feat(v2.3): add learn_writer to save user-contributed KB entries"
```

---

## Task 10: Attachments — Prompt Build Tests

**Files:**
- Test: `tests/test_attachments.py`

- [ ] **Step 1: Write tests**

Create `Dev/kb_chatbot/tests/test_attachments.py`:

```python
from Dev.kb_chatbot.prompt import Attachment, build_messages, _build_text_block
from Dev.kb_chatbot.chunker import Chunk


def _chunk():
    return Chunk(id="x", text="content",
                 metadata={"title": "Art", "url": "https://x.com", "product": "tradedesk", "category": "dealing"})


def test_text_attachment_included_in_message():
    att = Attachment(filename="notes.txt", media_type="text/plain",
                     data=b"log line 1\nlog line 2", is_image=False)
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="Why?",
                          attachments=[att])
    content = msgs[-1]["content"]
    assert isinstance(content, str)
    assert "log line 1" in content


def test_text_attachment_truncated_at_20000_chars():
    long_data = ("x" * 21_000).encode()
    att = Attachment(filename="big.txt", media_type="text/plain",
                     data=long_data, is_image=False)
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="?",
                          attachments=[att])
    content = msgs[-1]["content"]
    assert "[truncated]" in content
    # Original 21000 chars of x's should not all be present
    assert content.count("x") <= 20_000


def test_image_attachment_produces_list_content():
    att = Attachment(filename="screen.png", media_type="image/png",
                     data=b"\x89PNG\r\n\x1a\n", is_image=True)
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="What?",
                          attachments=[att])
    content = msgs[-1]["content"]
    assert isinstance(content, list)
    image_blocks = [b for b in content if b.get("type") == "image"]
    text_blocks = [b for b in content if b.get("type") == "text"]
    assert len(image_blocks) == 1
    assert len(text_blocks) == 1


def test_image_block_has_base64_data():
    import base64
    raw = b"\x89PNG\r\n"
    att = Attachment(filename="s.png", media_type="image/png", data=raw, is_image=True)
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="?",
                          attachments=[att])
    content = msgs[-1]["content"]
    img_block = next(b for b in content if b["type"] == "image")
    assert img_block["source"]["type"] == "base64"
    assert img_block["source"]["data"] == base64.b64encode(raw).decode()


def test_no_attachments_produces_string_content():
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="How?")
    assert isinstance(msgs[-1]["content"], str)


def test_five_attachment_limit_informational():
    # Just confirm build_messages doesn't crash with 5 attachments
    atts = [Attachment(filename=f"f{i}.txt", media_type="text/plain",
                       data=b"data", is_image=False) for i in range(5)]
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="?",
                          attachments=atts)
    assert msgs[-1] is not None
```

- [ ] **Step 2: Run tests**

```
python -m pytest Dev/kb_chatbot/tests/test_attachments.py -v
```

Expected: all PASSED (prompt.py was already updated in Task 3).

- [ ] **Step 3: Commit**

```
git add Dev/kb_chatbot/tests/test_attachments.py
git commit -m "test(v2.3): add attachment prompt-building tests"
```

---

## Task 11: GUI — Instant Startup (InitWorker)

**Files:**
- Modify: `gui.py`

This task has no unit test (Qt threading requires an event loop). Manual verification is the test.

- [ ] **Step 1: Add `InitWorker` class to `gui.py`**

Add this class after `IngestWorker` in `gui.py`:

```python
class InitWorker(QThread):
    """Loads ML models and warms up the Claude SDK client in the background.
    Emits ready(retriever) when complete so the GUI can unlock the input."""
    ready = Signal(object)   # emits the loaded Retriever
    status = Signal(str)     # progress messages for the status bar
    failed = Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings

    def run(self):
        try:
            self.status.emit("⟳ Initialising — loading models...")
            from Dev.kb_chatbot.retriever import Retriever
            retriever = Retriever(
                config.CHROMA_DIR,
                confidence_floor=self.settings.confidence_floor,
            )
            self.status.emit("⟳ Initialising — warming up Claude...")
            from Dev.kb_chatbot.prompt import build_system_prompt
            from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeProvider
            ClaudeCodeProvider().warm_up(build_system_prompt(), self.settings.default_model)
            self.ready.emit(retriever)
        except Exception as exc:
            log.exception("InitWorker failed")
            self.failed.emit(str(exc))
```

- [ ] **Step 2: Restructure `MainWindow.__init__` to show window before init**

Replace `MainWindow.__init__`:

```python
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Contoso KB Chatbot")
        self.resize(1100, 780)
        self.settings = settings_mod.load_settings()
        self.session = Session.new()
        self.worker: Optional[TurnWorker] = None
        self.ingest_worker: Optional[IngestWorker] = None
        self._retriever: Optional[Retriever] = None
        self._today_queries = 0
        self._today_tokens = 0
        self._learn_mode = False
        self._last_assistant_turn: Optional[Turn] = None
        self._build_ui()
        # Show window immediately, then init in background
        self._set_chat_enabled(False)
        self._start_init_worker()
```

- [ ] **Step 3: Add `_start_init_worker` and `_set_chat_enabled` methods**

Add to `MainWindow`:

```python
    def _start_init_worker(self):
        self._init_worker = InitWorker(self.settings)
        self._init_worker.ready.connect(self._on_init_ready)
        self._init_worker.status.connect(lambda msg: self.statusBar().showMessage(msg))
        self._init_worker.failed.connect(self._on_init_failed)
        self._init_worker.start()

    @Slot(object)
    def _on_init_ready(self, retriever):
        self._retriever = retriever
        self._set_chat_enabled(True)
        self.statusBar().showMessage("Ready")
        self._append("system", "Ready. Type a question below.", "#1b5e20", "SYSTEM:")

    @Slot(str)
    def _on_init_failed(self, err):
        self.statusBar().showMessage(f"Init failed: {err}")
        self._append("system", f"Initialisation failed: {err}", "#c62828", "ERROR:")

    def _set_chat_enabled(self, enabled: bool):
        self.input.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)
```

- [ ] **Step 4: Update `_send` to use `self._retriever` instead of creating a new one**

Replace the `try` block at the start of `_send`:

```python
    def _send(self):
        msg = self.input.text().strip()
        if not msg or self.worker or self._retriever is None:
            return
        self.input.clear()
        self._set_chat_enabled(False)
        self._append("user", msg, "#0d47a1", "YOU:")

        try:
            llm = ClaudeCodeProvider()
        except ClaudeCodeNotFoundError as exc:
            self._append("system", str(exc), "#c62828", "ERROR:")
            self._set_chat_enabled(True)
            return

        deps = Deps(retriever=self._retriever, llm=llm, usage_logger=_append_usage)
        filters = Filters(product=self.product_box.currentData() or None)
        model = self.model_box.currentData()
        self.worker = TurnWorker(msg, self.session, filters, model, deps)
        self.worker.signals.finished.connect(self._on_turn_done)
        self.worker.signals.failed.connect(self._on_turn_failed)
        self.worker.start()
```

- [ ] **Step 5: Remove the retriever `close()` call from `TurnWorker.run()`**

In `TurnWorker.run()`, remove the `finally` block that closes the retriever (we now share it):

```python
    def run(self):
        try:
            turn = handle_turn(self.user_msg, self.session, self.filters,
                                self.default_model, deps=self.deps)
            if self._cancel:
                turn = Turn(role="assistant", kind="abstain", content="Cancelled.")
                self.session.add(turn)
            self.signals.finished.emit(turn)
        except Exception as exc:
            log.exception("Turn failed")
            self.signals.failed.emit(str(exc))
        # Note: retriever is shared — do not close it here
```

- [ ] **Step 6: Update `_set_inputs_enabled` to use `_set_chat_enabled`**

Replace `_set_inputs_enabled` with:

```python
    def _set_inputs_enabled(self, enabled: bool):
        if self._retriever is not None:  # don't re-enable during init
            self._set_chat_enabled(enabled)
        for w in (self._act_reindex, self._act_settings, self._act_clear):
            w.setEnabled(enabled)
        self._act_stop.setEnabled(not enabled)
```

- [ ] **Step 7: Update `_build_ui` — remove `_warm_up_llm()` call and update Reindex tooltip**

In `_build_ui`, remove the call to `self._warm_up_llm()` at the end. Change the Reindex action:

```python
        self._act_reindex = QAction("Reindex", self)
        self._act_reindex.setToolTip("Run after adding new articles to the knowledge base")
        tb.addAction(self._act_reindex)
```

- [ ] **Step 8: Update `closeEvent` to close the shared retriever**

In `closeEvent`, before `event.accept()`, add:

```python
        if self._retriever:
            try:
                self._retriever.close()
            except Exception:
                pass
```

- [ ] **Step 9: Manual verification**

Launch the app:
```
python -m Dev.kb_chatbot.gui
```

Verify: window appears immediately (< 1 second). Status bar shows `"⟳ Initialising..."`. Input is greyed out. After 10–30 seconds, status shows `"Ready"` and input unlocks.

- [ ] **Step 10: Commit**

```
git add Dev/kb_chatbot/gui.py
git commit -m "feat(v2.3): instant startup — InitWorker loads models in background before unlocking chat"
```

---

## Task 12: GUI — QTextBrowser with Clickable Links

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Update imports in `gui.py`**

Replace the `QPlainTextEdit` import with `QTextBrowser`. In the PySide6 imports block, change:

```python
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QTextBrowser, QLineEdit, QToolBar,
    QStatusBar, QMessageBox, QDialog, QDialogButtonBox, QFormLayout,
    QFileDialog, QProgressBar,
)
```

Also add to top-level imports:

```python
import html as html_module
import re as re_module
```

- [ ] **Step 2: Replace `QPlainTextEdit` with `QTextBrowser` in `_build_ui`**

Change:

```python
        self.chat_view = QPlainTextEdit(); self.chat_view.setReadOnly(True)
        self.chat_view.setFont(QFont("Consolas", 10))
```

to:

```python
        self.chat_view = QTextBrowser()
        self.chat_view.setFont(QFont("Consolas", 10))
        self.chat_view.setOpenExternalLinks(True)
        self.chat_view.setReadOnly(True)
```

- [ ] **Step 3: Update `_append` to use HTML**

Replace the `_append` method:

```python
    def _append(self, role: str, text: str, colour: str, tag: str):
        ts = datetime.now().strftime("%H:%M:%S")
        safe_text = html_module.escape(text)
        if role == "ai":
            # Convert [Title](url) markdown links to HTML hyperlinks
            safe_text = re_module.sub(
                r'\[([^\]]+)\]\((https?://[^\)]+)\)',
                r'<a href="\2">\1</a>',
                safe_text,
            )
        # Preserve line breaks
        safe_text = safe_text.replace("\n", "<br>")
        block = (
            f'<p style="margin:4px 0; font-family:Consolas,monospace; font-size:10pt;">'
            f'<span style="color:#555;">{ts}</span> '
            f'<b style="color:{colour};">{html_module.escape(tag)}</b> '
            f'<span style="color:{colour};">{safe_text}</span>'
            f'</p>'
        )
        self.chat_view.append(block)
        self.chat_view.ensureCursorVisible()
```

- [ ] **Step 4: Manual verification**

Launch the app, ask a question. Verify:
- Links in bot responses are clickable (underlined)
- Clicking opens the Confluence URL in the default browser
- `[unverified]` text renders as plain text without a link

- [ ] **Step 5: Commit**

```
git add Dev/kb_chatbot/gui.py
git commit -m "feat(v2.3): switch chat view to QTextBrowser for clickable source links"
```

---

## Task 13: GUI — Attachment Bar and File Uploads

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Add attachment state and constants to `MainWindow`**

At the top of `gui.py` add:

```python
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_TEXT_EXTS  = {".md", ".txt", ".json", ".log"}
_ALL_EXTS   = _IMAGE_EXTS | _TEXT_EXTS
_MAX_IMAGE_BYTES = 4 * 1024 * 1024   # 4 MB
_MAX_TEXT_CHARS  = 20_000
_MAX_ATTACHMENTS = 5
```

In `MainWindow.__init__` (just after `self._learn_mode = False`):

```python
        self._attachments: list = []   # list of Attachment objects
```

- [ ] **Step 2: Add the attachment bar widget to `_build_ui`**

In `_build_ui`, before the `input_row` block, add:

```python
        # Attachment bar — hidden until files are added
        self._attach_bar = QWidget()
        attach_layout = QHBoxLayout(self._attach_bar)
        attach_layout.setContentsMargins(4, 2, 4, 2)
        attach_layout.setSpacing(6)
        self._attach_bar.setVisible(False)
        outer.addWidget(self._attach_bar)
```

Change the `input_row` to include a paperclip button:

```python
        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ask a question about the Contoso KB… (drag & drop files or Ctrl+V to attach)")
        self.input.returnPressed.connect(self._send)
        self._clip_btn = QPushButton("📎")
        self._clip_btn.setFixedWidth(36)
        self._clip_btn.setToolTip("Attach file (image or text)")
        self._clip_btn.clicked.connect(self._open_file_picker)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input)
        input_row.addWidget(self._clip_btn)
        input_row.addWidget(self.send_btn)
        outer.addLayout(input_row)
```

Enable drag-and-drop on the window:

```python
        self.setAcceptDrops(True)
```

- [ ] **Step 3: Add attachment methods to `MainWindow`**

```python
    # ── Attachments ──────────────────────────────────────────────────────────
    def _open_file_picker(self):
        if len(self._attachments) >= _MAX_ATTACHMENTS:
            return
        exts = " ".join(f"*{e}" for e in sorted(_ALL_EXTS))
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Attach file", "", f"Supported files ({exts})"
        )
        for p in paths:
            self._add_attachment_path(Path(p))

    def _add_attachment_path(self, path: Path):
        from Dev.kb_chatbot.prompt import Attachment
        if len(self._attachments) >= _MAX_ATTACHMENTS:
            self._append("system", f"Maximum {_MAX_ATTACHMENTS} attachments per message.", "#c62828", "SYSTEM:")
            return
        ext = path.suffix.lower()
        if ext not in _ALL_EXTS:
            self._append("system", f"Unsupported file type: {ext}", "#c62828", "SYSTEM:")
            return
        try:
            data = path.read_bytes()
        except Exception as exc:
            self._append("system", f"Could not read {path.name}: {exc}", "#c62828", "SYSTEM:")
            return
        is_image = ext in _IMAGE_EXTS
        if is_image and len(data) > _MAX_IMAGE_BYTES:
            self._append("system", f"{path.name} exceeds 4 MB limit — not attached.", "#c62828", "SYSTEM:")
            return
        media_type = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".gif": "image/gif", ".webp": "image/webp",
        }.get(ext, "text/plain")
        att = Attachment(filename=path.name, media_type=media_type, data=data, is_image=is_image)
        self._attachments.append(att)
        self._refresh_attach_bar()

    def _refresh_attach_bar(self):
        # Clear existing chips
        layout = self._attach_bar.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        # Add chips
        for i, att in enumerate(self._attachments):
            chip = QWidget()
            row = QHBoxLayout(chip)
            row.setContentsMargins(4, 2, 4, 2)
            row.setSpacing(3)
            lbl = QLabel(f"📎 {att.filename}")
            lbl.setStyleSheet("background:#e3f2fd; border-radius:4px; padding:2px 6px;")
            rm_btn = QPushButton("×")
            rm_btn.setFixedSize(20, 20)
            rm_btn.setStyleSheet("border:none; color:#555;")
            rm_btn.clicked.connect(lambda _, idx=i: self._remove_attachment(idx))
            row.addWidget(lbl)
            row.addWidget(rm_btn)
            layout.addWidget(chip)
        layout.addStretch()
        self._attach_bar.setVisible(bool(self._attachments))
        self._clip_btn.setEnabled(len(self._attachments) < _MAX_ATTACHMENTS)

    def _remove_attachment(self, idx: int):
        if 0 <= idx < len(self._attachments):
            self._attachments.pop(idx)
            self._refresh_attach_bar()

    # ── Drag and Drop ────────────────────────────────────────────────────────
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            self._add_attachment_path(Path(url.toLocalFile()))

    # ── Clipboard paste ──────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeySequence
        if event.matches(QKeySequence.Paste):
            clipboard = QApplication.clipboard()
            mime = clipboard.mimeData()
            if mime.hasImage():
                from Dev.kb_chatbot.prompt import Attachment
                import io
                img = clipboard.image()
                if not img.isNull():
                    buf = io.BytesIO()
                    ba = img.save  # QImage.save to buffer requires QBuffer
                    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
                    byte_array = QByteArray()
                    buffer = QBuffer(byte_array)
                    buffer.open(QIODevice.WriteOnly)
                    img.save(buffer, "PNG")
                    data = bytes(byte_array)
                    att = Attachment(filename="clipboard.png", media_type="image/png",
                                     data=data, is_image=True)
                    self._attachments.append(att)
                    self._refresh_attach_bar()
                    return
        super().keyPressEvent(event)
```

- [ ] **Step 4: Update `_send` to pass attachments and clear after send**

In `_send`, update `TurnWorker` creation to pass attachments, and clear them:

```python
        attachments = list(self._attachments)
        self._attachments.clear()
        self._refresh_attach_bar()

        deps = Deps(retriever=self._retriever, llm=llm, usage_logger=_append_usage,
                    attachments=attachments)
```

Update `Deps` in `orchestrator.py` to accept `attachments`, and pass them into `build_messages`. Add to `Deps` dataclass:

```python
@dataclass
class Deps:
    retriever: Retriever
    llm: LLMProvider
    usage_logger: Callable[[Turn], None] = lambda t: None
    clarifier: Optional[Callable[[str, list[Chunk]], str]] = None
    attachments: list = field(default_factory=list)
```

In `handle_turn`, update the `build_messages` call:

```python
            messages = build_messages(
                context_chunks=result.chunks,
                history=session.history_for_llm(config.MAX_HISTORY_TURNS),
                user_msg=user_msg + drift_note,
                attachments=deps.attachments or [],
            )
```

Also update `TurnWorker` to accept and forward `attachments` — update the `Deps` object creation in `_send`:

```python
        deps = Deps(
            retriever=self._retriever,
            llm=llm,
            usage_logger=_append_usage,
            attachments=attachments,
        )
```

Store filenames in the session turn. In `orchestrator.py`, update the `Turn` creation for answers:

```python
        turn = Turn(
            role="assistant",
            content=answer_text,
            kind="answer",
            attachments=[a.filename for a in (deps.attachments or [])],
            ...
        )
```

- [ ] **Step 5: Manual verification**

Launch app. Drag a PNG screenshot onto the window. Verify chip appears. Ask "What error is shown in this screenshot?" Verify the question sends with the image data in the message. Verify the bar clears after Send.

- [ ] **Step 6: Commit**

```
git add Dev/kb_chatbot/gui.py Dev/kb_chatbot/chat/orchestrator.py
git commit -m "feat(v2.3): add file/screenshot upload with drag-drop, paste, and attachment bar"
```

---

## Task 14: GUI — Learn Mode

**Files:**
- Modify: `gui.py`

- [ ] **Step 1: Add Learn Mode toolbar button and state to `_build_ui`**

In `_build_ui`, after the existing toolbar actions, add:

```python
        tb.addSeparator()
        self._act_learn = QAction("Learn Mode", self)
        self._act_learn.setCheckable(False)
        tb.addAction(self._act_learn)
        self._act_exit_learn = QAction("Exit Learn Mode", self)
        self._act_exit_learn.setVisible(False)
        tb.addAction(self._act_exit_learn)
```

Connect actions (add to the connect block at the bottom of `_build_ui`):

```python
        self._act_learn.triggered.connect(self._enter_learn_mode)
        self._act_exit_learn.triggered.connect(self._exit_learn_mode)
```

Add the feedback bar (below the chat view, hidden by default):

```python
        self._feedback_bar = QWidget()
        fb_layout = QHBoxLayout(self._feedback_bar)
        fb_layout.setContentsMargins(4, 4, 4, 4)
        self._btn_mark_correct = QPushButton("✓ Mark as Correct")
        self._btn_mark_correct.setStyleSheet("background:#e8f5e9; color:#2e7d32;")
        self._btn_correct_add = QPushButton("✎ Correct / Add to KB")
        self._btn_correct_add.setStyleSheet("background:#fff8e1; color:#f57f17;")
        fb_layout.addWidget(self._btn_mark_correct)
        fb_layout.addWidget(self._btn_correct_add)
        fb_layout.addStretch()
        self._feedback_bar.setVisible(False)
        outer.addWidget(self._feedback_bar)  # add after chat_view, before attach_bar

        self._btn_mark_correct.clicked.connect(self._on_mark_correct)
        self._btn_correct_add.clicked.connect(self._on_open_correction_editor)

        # Correction editor — hidden inline panel
        self._correction_panel = self._build_correction_panel()
        self._correction_panel.setVisible(False)
        outer.addWidget(self._correction_panel)
```

- [ ] **Step 2: Add `_build_correction_panel` method**

```python
    def _build_correction_panel(self) -> QWidget:
        panel = QWidget()
        panel.setStyleSheet("background:#fffde7; border:1px solid #f9a825; border-radius:4px;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)

        layout.addWidget(QLabel("Correct or extend the answer below:"))
        self._correction_text = QPlainTextEdit()
        self._correction_text.setFixedHeight(120)
        layout.addWidget(self._correction_text)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Product:"))
        self._correction_product = QComboBox()
        for p in config.PRODUCTS:
            self._correction_product.addItem(config.PRODUCT_DISPLAY.get(p, p), p)
        row1.addWidget(self._correction_product)
        row1.addWidget(QLabel("Topic:"))
        self._correction_topic = QLineEdit()
        self._correction_topic.setPlaceholderText("e.g. Dealing, Finance")
        row1.addWidget(self._correction_topic)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Source URL (optional):"))
        self._correction_url = QLineEdit()
        self._correction_url.setPlaceholderText("https://help.contoso.example/display/...")
        row2.addWidget(self._correction_url)
        layout.addLayout(row2)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save to KB")
        save_btn.setStyleSheet("background:#4caf50; color:white;")
        save_btn.clicked.connect(self._on_save_correction)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(lambda: self._correction_panel.setVisible(False))
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        return panel
```

- [ ] **Step 3: Add Learn Mode methods to `MainWindow`**

```python
    # ── Learn Mode ────────────────────────────────────────────────────────────
    def _enter_learn_mode(self):
        from PySide6.QtWidgets import QInputDialog, QLineEdit as _QLE
        from Dev.kb_chatbot.settings import check_learn_password
        pwd, ok = QInputDialog.getText(
            self, "Learn Mode", "Enter password:", _QLE.Password
        )
        if not ok:
            return
        if not check_learn_password(pwd, self.settings.learn_mode_hash):
            # Log failed attempt
            import json
            with open(config.USAGE_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({"kind": "learn_mode_failed_auth",
                                    "ts": datetime.now().isoformat()}) + "\n")
            QMessageBox.warning(self, "Access Denied", "Incorrect password.")
            return
        self._learn_mode = True
        self._act_learn.setVisible(False)
        self._act_exit_learn.setVisible(True)
        self._append("system", "Learn Mode active. Feedback controls will appear after each response.",
                     "#f57f17", "SYSTEM:")

    def _exit_learn_mode(self):
        self._learn_mode = False
        self._act_learn.setVisible(True)
        self._act_exit_learn.setVisible(False)
        self._feedback_bar.setVisible(False)
        self._correction_panel.setVisible(False)
        self._append("system", "Learn Mode exited.", "#1b5e20", "SYSTEM:")

    def _on_mark_correct(self):
        if self._last_assistant_turn is None:
            return
        from Dev.kb_chatbot.chat.learn_writer import write_learned_entry
        write_learned_entry(
            library_path=self.settings.library_path,
            product="other",
            topic="verified",
            title=f"Verified: {self._last_assistant_turn.content[:60]}",
            body_md=self._last_assistant_turn.content,
            url="",
            original_question=self._get_last_user_question(),
        )
        self._feedback_bar.setVisible(False)
        self._append("system", "Marked as correct — saved to Learn KB.", "#1b5e20", "SYSTEM:")

    def _on_open_correction_editor(self):
        if self._last_assistant_turn:
            self._correction_text.setPlainText(self._last_assistant_turn.content)
        self._correction_panel.setVisible(True)

    def _on_save_correction(self):
        from Dev.kb_chatbot.chat.learn_writer import write_learned_entry
        body = self._correction_text.toPlainText().strip()
        if not body:
            QMessageBox.warning(self, "Empty", "Please enter correction text.")
            return
        write_learned_entry(
            library_path=self.settings.library_path,
            product=self._correction_product.currentData(),
            topic=self._correction_topic.text().strip() or "general",
            title=f"Correction: {body[:60]}",
            body_md=body,
            url=self._correction_url.text().strip(),
            original_question=self._get_last_user_question(),
        )
        self._correction_panel.setVisible(False)
        self._feedback_bar.setVisible(False)
        self._append("system",
            "Saved to Learn KB. Run Reindex to make it searchable.",
            "#1b5e20", "SYSTEM:")

    def _get_last_user_question(self) -> str:
        for turn in reversed(self.session.turns):
            if turn.get("role") == "user":
                return turn.get("content", "")
        return ""
```

- [ ] **Step 4: Show feedback bar after each assistant response**

In `_on_turn_done`, after `self._append("ai", ...)`, add:

```python
        self._last_assistant_turn = turn
        if self._learn_mode and turn.kind == "answer":
            self._feedback_bar.setVisible(True)
            self._correction_panel.setVisible(False)
```

- [ ] **Step 5: Manual verification**

Launch app. Wait for init. Click "Learn Mode". Enter `YOUR_LEARN_PASSWORD_HERE`. Verify mode banner appears. Ask a question. Verify feedback buttons appear after answer. Click "✎ Correct / Add to KB". Enter a correction. Click "Save to KB". Verify a file appears in `library/learned/`. Click "Exit Learn Mode". Verify feedback bar hides.

- [ ] **Step 6: Commit**

```
git add Dev/kb_chatbot/gui.py
git commit -m "feat(v2.3): add Learn Mode with password gate, feedback controls, and correction editor"
```

---

## Task 15: Final Integration Smoke Test

- [ ] **Step 1: Run all new tests together**

```
python -m pytest Dev/kb_chatbot/tests/test_multi_turn.py Dev/kb_chatbot/tests/test_citations_url.py Dev/kb_chatbot/tests/test_suggestions.py Dev/kb_chatbot/tests/test_learn_mode.py Dev/kb_chatbot/tests/test_attachments.py -v
```

Expected: all PASSED.

- [ ] **Step 2: Run existing tests to confirm no regressions**

```
python -m pytest Dev/kb_chatbot/tests/ -v --ignore=Dev/kb_chatbot/tests/test_multi_turn.py --ignore=Dev/kb_chatbot/tests/test_citations_url.py --ignore=Dev/kb_chatbot/tests/test_suggestions.py --ignore=Dev/kb_chatbot/tests/test_learn_mode.py --ignore=Dev/kb_chatbot/tests/test_attachments.py
```

Expected: all existing tests PASSED.

- [ ] **Step 3: Manual end-to-end walkthrough**

1. Launch app — window appears in < 1s, status bar shows "Initialising..."
2. After ~15s, status shows "Ready", input unlocks
3. Ask "How do I book a retail deal?" — response has a clickable link
4. Ask "How do I reverse that?" — bot understands "that" refers to the deal (multi-turn)
5. Ask "something completely unrelated about API functions" — bot re-anchors correctly
6. Drag a PNG onto the window — chip appears in attachment bar
7. Ask "What error does this show?" — message sends with image
8. Ask "xyz abc" — bot shows suggestion list with related articles
9. Enter Learn Mode with correct password — feedback bar appears after next response
10. Click "Correct / Add to KB" — save correction — check `library/learned/` for the file
11. Exit Learn Mode — feedback bar disappears

- [ ] **Step 4: Final commit**

```
git add -u
git commit -m "feat: KB Chatbot v2.3 — multi-turn, source links, instant startup, uploads, Learn Mode, suggestions"
```
