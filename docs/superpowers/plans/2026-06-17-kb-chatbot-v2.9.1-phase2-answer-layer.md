# KB Chatbot v2.9.1 — Phase 2: Answer Layer (Ticket Completeness, Out-of-Scope, Output Scrub) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ticket answers complete and reliable (full on-ticket solution + root cause, every time), add a 3-tier out-of-scope response, scrub PII/secrets from the model's answer, reference ticket screenshots, and attach a related KB article when one exists.

**Architecture:** All changes live in the answer layer — `chat/orchestrator.py` (per-turn pipeline), `retriever.py` (sibling fetch already exists via `get_by_ticket_ids`), `prompt.py` (system prompt), `chat/ticket_redactor.py` (reuse its patterns for an output scrub), and `config.py` (constants). Phase 1 re-chunked tickets (each ticket = 1..N chunks sharing `ticket_id` + 0-based contiguous `chunk_index`, header on chunk 0, `has_images` flag). This phase reassembles the **whole ticket** for the answer (parent-document retrieval) so the LLM never sees a fragment.

**Tech Stack:** Python 3, `re`, pytest. Tests run with `scraper/venv/Scripts/python.exe -m pytest` from the repo root.

## Global Constraints

- **Completeness wins** for ticket answers — always surface the full on-ticket solution + root cause; never clip to save tokens.
- **Redaction/scrub tightens, never loosens.** The output scrub mirrors the redactor's email/phone/secret patterns but must NOT run the contextual name patterns (they would mangle legitimate prose/citations).
- **No images shown/stored.** Ticket screenshots are referenced via a link to the ticket page + a note only.
- **Parent-document contract (from Phase 1):** a ticket's chunks share `metadata["ticket_id"]` and have 0-based contiguous `metadata["chunk_index"]`; chunk 0 carries the staff/client header; chunk text leads with `Ticket #<id> — <title>`; chunks have no overlap. Reassembly fetches all siblings via `retriever.get_by_ticket_ids([tid])`, orders by `chunk_index`, and concatenates.
- **Both providers behave identically** (same context, same answer cap) — Claude and GPT-5.4.
- **Test runner:** `scraper/venv/Scripts/python.exe -m pytest <path> -v` from repo root. Imports use `from Dev.kb_chatbot...`.
- **Commit after each task.** Branch: `feat/kb-chatbot-v2.9.1` (already checked out; Phase 1 is committed at `e300313`).
- **No reindex/build in this phase** (that is Phase 4). Tests use `FakeRetriever`/`FakeProvider` and the tiny fixture library — no embedding needed.

---

### Task 1: Pure ticket-assembly helper

**Files:**
- Modify: `Dev/kb_chatbot/retriever.py` (add a module-level `assemble_ticket` function)
- Test: `Dev/kb_chatbot/tests/test_retriever_assembly.py` (new)

**Interfaces:**
- Consumes: `Chunk` (id, text, metadata) from Phase 1's ticket chunks.
- Produces: `assemble_ticket(chunks: list[Chunk]) -> Chunk` — given all chunks of ONE ticket, returns a single Chunk with the full ticket text (ordered by `chunk_index`, title line de-duplicated) and chunk 0's metadata with `chunk_index` set to 0. Tasks 2-3 call this.

- [ ] **Step 1: Write the failing test**

Create `Dev/kb_chatbot/tests/test_retriever_assembly.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.retriever import assemble_ticket
from Dev.kb_chatbot.chunker import Chunk


def _tc(idx, body, **md):
    text = "Ticket #75919 — GetWebDeal missing buy amount"
    if idx == 0:
        text += "\nClient: Acme · CSQA owner: p.shah"
    text += f"\n\n{body}"
    meta = {"kind": "ticket", "ticket_id": "75919", "title": "Ticket #75919",
            "url": "https://support.contoso.example/edit_bug.aspx?id=75919",
            "chunk_index": idx, "has_images": False}
    meta.update(md)
    return Chunk(id=f"ticket_h:{idx}", text=text, metadata=meta)


def test_assemble_orders_by_chunk_index_and_dedupes_title():
    # deliberately out of order
    chunks = [_tc(2, "step three end"), _tc(0, "Problem: buy amount null"),
              _tc(1, "Resolution: updated the value")]
    full = assemble_ticket(chunks)
    # header from chunk 0 present exactly once
    assert full.text.count("Client: Acme") == 1
    # title line appears once, not three times
    assert full.text.count("Ticket #75919 — GetWebDeal missing buy amount") == 1
    # all three bodies present in order
    i0 = full.text.index("buy amount null")
    i1 = full.text.index("updated the value")
    i2 = full.text.index("step three end")
    assert i0 < i1 < i2
    assert full.metadata["ticket_id"] == "75919"
    assert full.metadata["chunk_index"] == 0


def test_assemble_single_chunk_returns_equivalent():
    [only] = [_tc(0, "Problem: p\n\nResolution: r")]
    full = assemble_ticket([only])
    assert "Problem: p" in full.text and "Resolution: r" in full.text
    assert full.metadata["ticket_id"] == "75919"


def test_assemble_preserves_has_images_flag():
    chunks = [_tc(0, "Problem: p", has_images=True), _tc(1, "Resolution: r", has_images=True)]
    full = assemble_ticket(chunks)
    assert full.metadata["has_images"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_retriever_assembly.py -v`
Expected: FAIL with `ImportError: cannot import name 'assemble_ticket'`.

- [ ] **Step 3: Implement `assemble_ticket`**

In `Dev/kb_chatbot/retriever.py`, add after the imports / before the `Retriever` class (module level):

```python
def _strip_title_line(text: str) -> str:
    """Drop the leading 'Ticket #<id> — <title>' line (and the blank line after it)
    from a non-first chunk, leaving just its body segment."""
    parts = text.split("\n\n", 1)
    return parts[1].strip() if len(parts) == 2 else text.strip()


def assemble_ticket(chunks: list[Chunk]) -> Chunk:
    """Reassemble the full ticket from its sibling chunks (parent-document
    retrieval). Orders by chunk_index; chunk 0 (with the staff/client header)
    leads, subsequent chunks contribute their body segment only. Returns one
    Chunk carrying chunk 0's metadata (chunk_index normalised to 0)."""
    ordered = sorted(chunks, key=lambda c: int(c.metadata.get("chunk_index", 0)))
    head = ordered[0]
    text = head.text.strip()
    for c in ordered[1:]:
        seg = _strip_title_line(c.text)
        if seg:
            text += "\n\n" + seg
    meta = dict(head.metadata)
    meta["chunk_index"] = 0
    return Chunk(id=head.id, text=text, metadata=meta)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_retriever_assembly.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/retriever.py Dev/kb_chatbot/tests/test_retriever_assembly.py
git commit -m "feat(v2.9.1): assemble_ticket helper for parent-document reassembly"
```

---

### Task 2: Orchestrator parent-document expansion

**Files:**
- Modify: `Dev/kb_chatbot/chat/orchestrator.py`
- Test: `Dev/kb_chatbot/tests/test_orchestrator_tickets.py` (new)

**Interfaces:**
- Consumes: `assemble_ticket` (Task 1); `retriever.get_by_ticket_ids` (exists).
- Produces: `_expand_ticket_chunks(chunks: list[Chunk], retriever) -> list[Chunk]` — replaces each ticket fragment in `chunks` with the assembled full ticket (one per `ticket_id`, at the position of first occurrence), leaving non-ticket chunks untouched. Wired into `handle_turn` so `result.chunks` is expanded before `build_messages`.

- [ ] **Step 1: Write the failing test**

Create `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.retriever import Filters, RetrievalResult
from Dev.kb_chatbot.llm.fake_provider import FakeProvider

URL = "https://support.contoso.example/edit_bug.aspx?id=75919"


def _frag(idx, body, has_images=False):
    text = "Ticket #75919 — GetWebDeal missing buy amount"
    if idx == 0:
        text += "\nClient: Acme · CSQA owner: p.shah"
    text += f"\n\n{body}"
    return Chunk(id=f"ticket_h:{idx}", text=text, metadata={
        "kind": "ticket", "ticket_id": "75919", "title": "Ticket #75919",
        "url": URL, "category": "api", "product": "tradedesk",
        "chunk_index": idx, "has_images": has_images})


# All three fragments of the ticket; retrieve() returns only the middle one.
_ALL = [_frag(0, "Problem: buy amount came back null"),
        _frag(1, "Root cause: the mapping dropped the field"),
        _frag(2, "Resolution: re-added the field and redeployed")]


class FragmentRetriever:
    """retrieve() surfaces ONLY chunk 1 (a fragment); get_by_ticket_ids returns all."""
    def __init__(self):
        self.captured = None
    def retrieve(self, query, filters):
        return RetrievalResult(chunks=[_ALL[1]], rerank_top_score=0.9)
    def get_by_ids(self, ids):
        return []
    def get_by_ticket_ids(self, tids):
        return list(_ALL) if "75919" in [str(t) for t in tids] else []
    def retrieve_quick(self, query, limit=10):
        return []
    def suggest(self, query, top_k=5):
        return []


def test_ticket_answer_sees_full_ticket_not_fragment():
    """The model must receive the WHOLE ticket (problem + root cause + resolution),
    even though retrieval only surfaced one fragment."""
    llm = FakeProvider(canned_text=f"ok [Ticket #75919]({URL})")
    d = Deps(retriever=FragmentRetriever(), llm=llm)
    turn = handle_turn("why did GetWebDeal return null buy amount",
                       Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "answer"
    # The single user message the LLM saw must contain all three fragment bodies.
    sent = llm.calls[-1]["messages"][-1]["content"]
    assert "buy amount came back null" in sent      # problem (chunk 0)
    assert "the mapping dropped the field" in sent   # root cause (chunk 1)
    assert "re-added the field and redeployed" in sent  # resolution (chunk 2)
    # ticket appears once in the retrieved set, not as 3 fragments
    assert turn.retrieved_ids.count("ticket_h:0") <= 1
```

(Note: `FakeProvider` records each call's kwargs in `.calls`; the user message is the last message's `content`. If `FakeProvider.calls` does not capture `messages`, see Task 2 Step 3a.)

- [ ] **Step 2: Run test to verify it fails**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator_tickets.py::test_ticket_answer_sees_full_ticket_not_fragment -v`
Expected: FAIL (the LLM only sees chunk 1's body; "buy amount came back null" and "re-added the field" are absent).

- [ ] **Step 3a: Verify `FakeProvider` records messages (prerequisite)**

Open `Dev/kb_chatbot/llm/fake_provider.py`. Confirm `chat(...)` appends the call (including `messages`) to `self.calls`. If `self.calls` entries do not include `messages`, modify `chat` to record them:

```python
    def chat(self, *, messages, model, system_prompt, max_tokens=1024):
        self.calls.append({"messages": messages, "model": model,
                           "system_prompt": system_prompt, "max_tokens": max_tokens})
        # ... existing return of the canned LLMResponse ...
```

Run the existing fake/provider tests to confirm no regression:
Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_llm.py -v`
Expected: PASS.

- [ ] **Step 3b: Implement `_expand_ticket_chunks` and wire it in**

In `Dev/kb_chatbot/chat/orchestrator.py`, add the import at the top:

```python
from Dev.kb_chatbot.retriever import Retriever, Filters, assemble_ticket
```

Add this helper near `_merge_chunks`:

```python
def _expand_ticket_chunks(chunks: list[Chunk], retriever) -> list[Chunk]:
    """Replace each ticket fragment with the full assembled ticket (parent-document
    retrieval). One assembled chunk per ticket_id, kept at the position of first
    occurrence; non-ticket chunks are left untouched; order is otherwise preserved."""
    out: list[Chunk] = []
    seen_tickets: set[str] = set()
    for c in chunks:
        tid = c.metadata.get("ticket_id") if c.metadata.get("kind") == "ticket" else None
        if not tid:
            out.append(c)
            continue
        if tid in seen_tickets:
            continue
        seen_tickets.add(tid)
        siblings = retriever.get_by_ticket_ids([tid]) or [c]
        out.append(assemble_ticket(siblings))
    return out
```

Then, in `handle_turn`, expand `result.chunks` right BEFORE the `build_messages` call (inside the `if not result.abstain_reason:` block, after the clarify gate, immediately before `messages = build_messages(...)`):

```python
        result.chunks = _expand_ticket_chunks(result.chunks, deps.retriever)
        try:
            messages = build_messages(
                context_chunks=result.chunks,
                ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator_tickets.py Dev/kb_chatbot/tests/test_orchestrator.py -v`
Expected: PASS (new ticket test + all pre-existing orchestrator tests; the continuity tests still pass because their `get_by_ticket_ids` returns the single chunk, which `assemble_ticket` returns unchanged and `retrieved_ids` still contains `ticket_focus`).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/llm/fake_provider.py Dev/kb_chatbot/tests/test_orchestrator_tickets.py
git commit -m "feat(v2.9.1): parent-document expansion — assemble full ticket into context"
```

---

### Task 3: Raise the answer-length cap

**Files:**
- Modify: `Dev/kb_chatbot/config.py`, `Dev/kb_chatbot/chat/orchestrator.py`
- Test: `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`

**Interfaces:**
- Produces: `config.ANSWER_MAX_TOKENS = 2048`; `handle_turn` passes `max_tokens=config.ANSWER_MAX_TOKENS` to `deps.llm.chat`.

- [ ] **Step 1: Write the failing test**

Append to `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`:

```python
def test_answer_uses_raised_max_tokens():
    from Dev.kb_chatbot import config
    llm = FakeProvider(canned_text=f"ok [Ticket #75919]({URL})")
    d = Deps(retriever=FragmentRetriever(), llm=llm)
    handle_turn("why did GetWebDeal return null buy amount",
                Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert llm.calls[-1]["max_tokens"] == config.ANSWER_MAX_TOKENS
    assert config.ANSWER_MAX_TOKENS >= 2048
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator_tickets.py::test_answer_uses_raised_max_tokens -v`
Expected: FAIL (`config` has no `ANSWER_MAX_TOKENS`, and the call uses the hardcoded `1024`).

- [ ] **Step 3: Add the constant and use it**

In `Dev/kb_chatbot/config.py`, add under the retrieval defaults section:

```python
ANSWER_MAX_TOKENS = 2048  # full ticket resolutions can exceed 1024; completeness wins (v2.9.1)
```

In `Dev/kb_chatbot/chat/orchestrator.py`, change the `deps.llm.chat(...)` call's `max_tokens=1024` to:

```python
                max_tokens=config.ANSWER_MAX_TOKENS,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator_tickets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_orchestrator_tickets.py
git commit -m "feat(v2.9.1): raise answer cap to ANSWER_MAX_TOKENS=2048 (completeness wins)"
```

---

### Task 4: Output-side PII/secret scrub

**Files:**
- Modify: `Dev/kb_chatbot/chat/ticket_redactor.py` (add `scrub_answer`), `Dev/kb_chatbot/chat/orchestrator.py`
- Test: `Dev/kb_chatbot/tests/test_ticket_redactor.py`, `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`

**Interfaces:**
- Produces: `scrub_answer(text: str) -> str` in `ticket_redactor.py` — applies email / `_CRED_KV` / `_CRED_LABEL` / `_redact_secret_shapes` / phone (NOT the name patterns, NOT `_DROP_LINE`, NOT `known_terms`). `handle_turn` calls it on `resp.text` before citation validation.

- [ ] **Step 1: Write the failing tests**

Append to `Dev/kb_chatbot/tests/test_ticket_redactor.py`:

```python
from Dev.kb_chatbot.chat.ticket_redactor import scrub_answer

def test_scrub_answer_removes_email_and_secret():
    out = scrub_answer("Contact bob@acme.com with key sk_live_AbCd1234EfGh5678WxYz")
    assert "bob@acme.com" not in out
    assert "sk_live_AbCd1234EfGh5678WxYz" not in out

def test_scrub_answer_keeps_normal_prose_and_links():
    text = "Open the dealing screen. See [Ticket #5](https://support.contoso.example/x)."
    out = scrub_answer(text)
    assert "Open the dealing screen." in out
    assert "[Ticket #5](https://support.contoso.example/x)" in out

def test_scrub_answer_does_not_redact_capitalized_names_in_prose():
    # name patterns must NOT run here (would mangle legitimate staff usernames/prose)
    out = scrub_answer("The CSQA owner p.shah handled this; ask Sarah on the team.")
    assert "p.shah" in out
    assert "Sarah" in out
```

Append to `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`:

```python
def test_orchestrator_scrubs_answer_before_render():
    llm = FakeProvider(canned_text=f"resolved [Ticket #75919]({URL}) email leaked@acme.com")
    d = Deps(retriever=FragmentRetriever(), llm=llm)
    turn = handle_turn("why did GetWebDeal return null buy amount",
                       Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert "leaked@acme.com" not in turn.content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_redactor.py -k scrub_answer Dev/kb_chatbot/tests/test_orchestrator_tickets.py::test_orchestrator_scrubs_answer_before_render -v`
Expected: FAIL (`scrub_answer` undefined; the leaked email appears in the answer).

- [ ] **Step 3: Implement `scrub_answer` and call it**

In `Dev/kb_chatbot/chat/ticket_redactor.py`, add at the end of the file:

```python
def scrub_answer(text: str) -> str:
    """Defense-in-depth: strip emails / credential pairs / labelled secrets /
    secret-shaped tokens / phones from an LLM answer before it is shown or
    persisted. Deliberately does NOT run the contextual name patterns or
    known_terms — internal staff usernames and ordinary prose must survive,
    and citations must stay intact."""
    if not text:
        return ""
    out_lines: list[str] = []
    for line in text.replace("\r", "").split("\n"):
        line = _EMAIL.sub("[redacted]", line)
        line = _CRED_KV.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", line)
        line = _CRED_LABEL.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", line)
        line = _redact_secret_shapes(line)
        line = _PHONE.sub("[redacted]", line)
        out_lines.append(line)
    return "\n".join(out_lines)
```

In `Dev/kb_chatbot/chat/orchestrator.py`, add the import:

```python
from Dev.kb_chatbot.chat.ticket_redactor import scrub_answer
```

In `handle_turn`, scrub the response before validation. Change:

```python
        vr = validate_citations(resp.text, result.chunks)
```
to:

```python
        vr = validate_citations(scrub_answer(resp.text), result.chunks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_redactor.py Dev/kb_chatbot/tests/test_orchestrator_tickets.py -v`
Expected: PASS (the `_PHONE` pattern must not eat the citation — verify `test_scrub_answer_keeps_normal_prose_and_links` passes; if a long digit run in a URL is hit, the URL here has none).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/chat/ticket_redactor.py Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_ticket_redactor.py Dev/kb_chatbot/tests/test_orchestrator_tickets.py
git commit -m "feat(v2.9.1): output-side PII/secret scrub on answers (defense-in-depth)"
```

---

### Task 5: Three-tier out-of-scope response

**Files:**
- Modify: `Dev/kb_chatbot/config.py`, `Dev/kb_chatbot/chat/orchestrator.py`
- Test: `Dev/kb_chatbot/tests/test_orchestrator_scope.py` (new)

**Interfaces:**
- Produces: `config.OUT_OF_SCOPE_FLOOR = 0.02` (below `CONFIDENCE_FLOOR = 0.06`); `orchestrator.OUT_OF_SCOPE_MESSAGE`. In `handle_turn`: (a) the rewrite escalation only runs when `result.rerank_top_score >= config.OUT_OF_SCOPE_FLOOR` (clearly-unrelated queries don't get a rephrase); (b) the abstain branch returns the out-of-scope turn (no suggestions, no clarify) when `rerank_top_score < config.OUT_OF_SCOPE_FLOOR`.

- [ ] **Step 1: Write the failing tests**

Create `Dev/kb_chatbot/tests/test_orchestrator_scope.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps, OUT_OF_SCOPE_MESSAGE
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.retriever import Filters, RetrievalResult
from Dev.kb_chatbot.llm.fake_provider import FakeProvider


def _kb(title, url):
    return Chunk(id="k", text="content",
                 metadata={"product": "tradedesk", "category": "dealing",
                           "title": title, "url": url})


class ScopeRetriever:
    """abstains with a configurable score; suggest returns one article."""
    def __init__(self, score):
        self.score = score
    def retrieve(self, query, filters):
        return RetrievalResult(chunks=[], abstain_reason="no_relevant_kb_match",
                               rerank_top_score=self.score)
    def get_by_ids(self, ids): return []
    def get_by_ticket_ids(self, tids): return []
    def retrieve_quick(self, query, limit=10): return []
    def suggest(self, query, top_k=5):
        return [_kb("Booking a Spot Deal", "https://help.contoso.example/spot")]


def test_clearly_unrelated_returns_out_of_scope_no_suggestions():
    d = Deps(retriever=ScopeRetriever(config.OUT_OF_SCOPE_FLOOR - 0.005),
             llm=FakeProvider(canned_text="should not be seen"))
    turn = handle_turn("what is the boiling point of helium today",
                       Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "abstain"
    assert turn.content == OUT_OF_SCOPE_MESSAGE
    assert "help.contoso.example/spot" not in turn.content  # no suggestions for out-of-scope


def test_related_but_weak_still_suggests():
    # score between OUT_OF_SCOPE_FLOOR and CONFIDENCE_FLOOR -> suggestions path (not scope msg)
    score = (config.OUT_OF_SCOPE_FLOOR + config.CONFIDENCE_FLOOR) / 2
    d = Deps(retriever=ScopeRetriever(score),
             llm=FakeProvider(canned_text="should not be seen"))
    turn = handle_turn("how do I configure dealing spreads maybe",
                       Session.new(), Filters(product="tradedesk"),
                       "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "abstain"
    assert turn.content != OUT_OF_SCOPE_MESSAGE
    assert "help.contoso.example/spot" in turn.content  # suggestions present


def test_out_of_scope_skips_rewrite_escalation():
    calls = {"n": 0}
    def rewriter(user_msg, history):
        calls["n"] += 1
        return None
    d = Deps(retriever=ScopeRetriever(config.OUT_OF_SCOPE_FLOOR - 0.005),
             llm=FakeProvider(canned_text="x"), rewriter=rewriter)
    s = Session.new()
    s.add_user("earlier question")  # give history so rewrite WOULD fire if allowed
    handle_turn("totally unrelated astrophysics question here",
                s, Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert calls["n"] == 0  # no rephrase for clearly-out-of-scope
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator_scope.py -v`
Expected: FAIL (`OUT_OF_SCOPE_MESSAGE` undefined; out-of-scope path not implemented).

- [ ] **Step 3: Implement the tier**

In `Dev/kb_chatbot/config.py`, add under the retrieval defaults:

```python
OUT_OF_SCOPE_FLOOR = 0.02   # below this rerank score the query is treated as outside the KB scope
```

In `Dev/kb_chatbot/chat/orchestrator.py`, add the message constant near `ABSTAIN_MESSAGE`:

```python
OUT_OF_SCOPE_MESSAGE = (
    "That's outside the scope of the Contoso knowledge base — it covers the API, "
    "TradeDesk, SalesHub, Web2, Web4 and related product documentation and support tickets. "
    "If your question is about one of those, try naming the product and what you're trying to do."
)
```

Gate the rewrite escalation on the score — change the escalation condition:

```python
    if (result.abstain_reason and deps.rewriter is not None and history
            and result.rerank_top_score >= config.OUT_OF_SCOPE_FLOOR):
```

In the abstain branch (the code after the `if not result.abstain_reason:` block), add the out-of-scope check as the FIRST statement of that branch, before the clarify-from-quick / short-query / suggestions logic:

```python
    if result.rerank_top_score < config.OUT_OF_SCOPE_FLOOR:
        turn = Turn(role="assistant", kind="abstain", content=OUT_OF_SCOPE_MESSAGE)
        session.add(turn)
        deps.usage_logger(turn)
        return turn
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator_scope.py Dev/kb_chatbot/tests/test_orchestrator.py -v`
Expected: PASS. (Pre-existing `test_abstain_when_retrieval_below_floor` uses score `0.99`-floor retrieval → its `rerank_top_score` defaults to `0.0`, which is `< OUT_OF_SCOPE_FLOOR`. That test asserts `ABSTAIN_MESSAGE`; it will now get `OUT_OF_SCOPE_MESSAGE`. **Update that test** to assert `OUT_OF_SCOPE_MESSAGE` and import it — its query "quantum field theory equations" IS genuinely out-of-scope, so the new behavior is correct.)

Update in `Dev/kb_chatbot/tests/test_orchestrator.py`: change the import to add `OUT_OF_SCOPE_MESSAGE`, and in `test_abstain_when_retrieval_below_floor` change `assert turn.content == ABSTAIN_MESSAGE` to `assert turn.content == OUT_OF_SCOPE_MESSAGE`. Similarly `test_abstain_with_suggestions_when_suggest_returns_chunks` uses score `0.0` → now out-of-scope; change its query to a related one by stubbing the score: add `d.retriever.retrieve = lambda q, f: RetrievalResult(chunks=[], abstain_reason="no_relevant_kb_match", rerank_top_score=(config.OUT_OF_SCOPE_FLOOR + config.CONFIDENCE_FLOOR)/2)` before the call and import `config` + `RetrievalResult`, so it stays in the suggestions tier.

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_orchestrator_scope.py Dev/kb_chatbot/tests/test_orchestrator.py
git commit -m "feat(v2.9.1): 3-tier out-of-scope (scope message / clarify+suggest / answer)"
```

---

### Task 6: Ticket screenshot link-note

**Files:**
- Modify: `Dev/kb_chatbot/chat/orchestrator.py`
- Test: `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`

**Interfaces:**
- Produces: a deterministic note appended to a ticket answer when a used ticket chunk has `metadata["has_images"]` true. `IMAGE_NOTE_TEMPLATE` constant in `orchestrator.py`.

- [ ] **Step 1: Write the failing test**

Append to `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`:

```python
class ImageTicketRetriever(FragmentRetriever):
    def retrieve(self, query, filters):
        return RetrievalResult(chunks=[_frag(0, "Problem: see screenshot", has_images=True)],
                               rerank_top_score=0.9)
    def get_by_ticket_ids(self, tids):
        return [_frag(0, "Problem: see screenshot", has_images=True),
                _frag(1, "Resolution: per the image", has_images=True)] \
            if "75919" in [str(t) for t in tids] else []


def test_ticket_with_images_appends_screenshot_note():
    llm = FakeProvider(canned_text=f"resolved [Ticket #75919]({URL})")
    d = Deps(retriever=ImageTicketRetriever(), llm=llm)
    turn = handle_turn("why did GetWebDeal return null buy amount",
                       Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "answer"
    assert "screenshot" in turn.content.lower()
    assert URL in turn.content           # links to the ticket
    # no image bytes/paths surfaced
    assert "data:image" not in turn.content and "attachments/" not in turn.content


def test_ticket_without_images_has_no_note():
    llm = FakeProvider(canned_text=f"resolved [Ticket #75919]({URL})")
    d = Deps(retriever=FragmentRetriever(), llm=llm)  # has_images=False
    turn = handle_turn("why did GetWebDeal return null buy amount",
                       Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert "screenshot" not in turn.content.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator_tickets.py -k screenshot -v`
Expected: FAIL (no note appended).

- [ ] **Step 3: Implement the note**

In `Dev/kb_chatbot/chat/orchestrator.py`, add the template near the other message constants:

```python
IMAGE_NOTE_TEMPLATE = (
    "\n\n📎 This ticket includes a screenshot that may hold additional detail not in the text — "
    "open the ticket to view it: [Ticket #{tid}]({url})"
)
```

In `handle_turn`, after `answer_text` is finalised (after the low-confidence footer block, before constructing the answer `Turn`), append the note for the first used ticket chunk that has images:

```python
        for c in result.chunks:
            if c.metadata.get("kind") == "ticket" and c.metadata.get("has_images") \
                    and c.metadata.get("url"):
                answer_text += IMAGE_NOTE_TEMPLATE.format(
                    tid=c.metadata.get("ticket_id", ""), url=c.metadata["url"])
                break
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator_tickets.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_orchestrator_tickets.py
git commit -m "feat(v2.9.1): append ticket screenshot link-note when ticket has images (PII-safe)"
```

---

### Task 7: KB article alongside a ticket answer

**Files:**
- Modify: `Dev/kb_chatbot/chat/orchestrator.py`
- Test: `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`

**Interfaces:**
- Produces: `_ensure_kb_alongside(query, chunks, retriever) -> list[Chunk]` — when `chunks` contains a ticket but no non-ticket (KB) chunk, append the top non-ticket chunk from `retriever.retrieve_quick(query)` (best-effort; none added if no KB chunk exists). Called in `handle_turn` right after `_expand_ticket_chunks`.

- [ ] **Step 1: Write the failing test**

Append to `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`:

```python
class TicketPlusKbRetriever(FragmentRetriever):
    def retrieve_quick(self, query, limit=10):
        return [Chunk(id="kb1", text="How-to: GetWebDeal fields",
                      metadata={"product": "tradedesk", "category": "api",
                                "title": "GetWebDeal How-To",
                                "url": "https://help.contoso.example/getwebdeal"})]


def test_kb_article_attached_alongside_ticket():
    llm = FakeProvider(canned_text=f"resolved [Ticket #75919]({URL})")
    d = Deps(retriever=TicketPlusKbRetriever(), llm=llm)
    handle_turn("why did GetWebDeal return null buy amount",
                Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    sent = llm.calls[-1]["messages"][-1]["content"]
    assert "GetWebDeal How-To" in sent            # KB article merged into context
    assert "https://help.contoso.example/getwebdeal" in sent


def test_no_kb_attached_when_none_exists():
    llm = FakeProvider(canned_text=f"resolved [Ticket #75919]({URL})")
    d = Deps(retriever=FragmentRetriever(), llm=llm)  # retrieve_quick returns []
    turn = handle_turn("why did GetWebDeal return null buy amount",
                       Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "answer"   # no crash, no KB added
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator_tickets.py -k kb -v`
Expected: FAIL (`GetWebDeal How-To` not in the sent context).

- [ ] **Step 3: Implement KB-alongside**

In `Dev/kb_chatbot/chat/orchestrator.py`, add the helper near `_expand_ticket_chunks`:

```python
def _ensure_kb_alongside(query: str, chunks: list[Chunk], retriever) -> list[Chunk]:
    """If the context has a ticket but no KB article, attach the best-matching KB
    chunk (best-effort, 'if there is one'). Reuses the wide-net retrieve_quick."""
    has_ticket = any(c.metadata.get("kind") == "ticket" for c in chunks)
    has_kb = any(c.metadata.get("kind") != "ticket" for c in chunks)
    if not has_ticket or has_kb:
        return chunks
    seen = {c.id for c in chunks}
    for cand in retriever.retrieve_quick(query, limit=10):
        if cand.metadata.get("kind") != "ticket" and cand.metadata.get("url") \
                and cand.id not in seen:
            return [*chunks, cand]
    return chunks
```

Wire it in `handle_turn` immediately after the `_expand_ticket_chunks` line:

```python
        result.chunks = _expand_ticket_chunks(result.chunks, deps.retriever)
        result.chunks = _ensure_kb_alongside(retrieval_query, result.chunks, deps.retriever)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator_tickets.py Dev/kb_chatbot/tests/test_orchestrator.py -v`
Expected: PASS (the pre-existing tests have no ticket in context, so `_ensure_kb_alongside` is a no-op for them).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_orchestrator_tickets.py
git commit -m "feat(v2.9.1): attach a related KB article alongside ticket answers (best-effort)"
```

---

### Task 8: Expert-format ticket prompt

**Files:**
- Modify: `Dev/kb_chatbot/prompt.py`
- Test: `Dev/kb_chatbot/tests/test_prompt.py`

**Interfaces:**
- Produces: an updated `SYSTEM_PROMPT` with an explicit ticket-answer structure (Problem → Root cause → Resolution steps with citations → KB references → screenshot note → Sources). The locked-text test is updated to match.

- [ ] **Step 1: Inspect and update the locked-text test**

Open `Dev/kb_chatbot/tests/test_prompt.py` and read `test_system_prompt_locked_text_v23` (it pins exact prompt text). It will break when `SYSTEM_PROMPT` changes. Convert it from an exact-equality check to assertions on the key invariants that must remain, plus the new structure. Replace its body with:

```python
def test_system_prompt_locked_text_v23():
    p = build_system_prompt()
    # invariants that must never regress
    assert "only use facts from the CONTEXT block" in p
    assert 'I don\'t have enough information in the knowledge base' in p
    assert "[Article Title](url)" in p
    # new v2.9.1 expert ticket structure
    assert "Root cause" in p
    assert "Sources:" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_prompt.py::test_system_prompt_locked_text_v23 -v`
Expected: FAIL (`Root cause` not yet in the prompt).

- [ ] **Step 3: Update the prompt**

In `Dev/kb_chatbot/prompt.py`, replace rule 7 (the "Format:" rule) of `SYSTEM_PROMPT` with a ticket-aware structure:

```
7. Format: lead with a one-sentence direct answer. For an issue/ticket-based answer, structure it as: **Problem** (what went wrong) → **Root cause** (why it happened, if the ticket states it) → **Resolution** (every step, in order, each factual claim ending with its [Title](url) or [Ticket #<id>](url) citation) → any relevant **KB reference** links → then a "Searched:" footnote naming the product(s) considered, and a "Sources: #<id>, ..." line if any step drew on a ticket. Use ALL relevant CONTEXT entries; never truncate a procedure. For a pure how-to (no ticket), the numbered-steps form is sufficient.
```

(Leave all other rules unchanged; the completeness rule 6 and citation rules 3/11 still apply.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_prompt.py -v`
Expected: PASS (update any other assertion in `test_prompt.py` that pinned the old rule-7 wording verbatim; keep assertions about context-formatting helpers unchanged).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/prompt.py Dev/kb_chatbot/tests/test_prompt.py
git commit -m "feat(v2.9.1): expert ticket-answer format (Problem/Root cause/Resolution/KB/Sources)"
```

---

### Task 9: Full regression + ticket-reliability integration test

**Files:**
- Test: `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`

**Interfaces:**
- Consumes everything above.
- Produces: a determinism test proving the same question + a light rephrase both return a complete, non-abstain ticket answer (the alpha-reported partial→none→partial bug is gone).

- [ ] **Step 1: Write the failing/seam test**

Append to `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`:

```python
def test_same_ticket_question_is_consistent_across_rephrasings():
    """The alpha bug: same question yields partial → nothing → partial. With parent
    expansion + a confident ticket match, both phrasings return the full answer."""
    for phrasing in ["why did GetWebDeal return null buy amount",
                     "GetWebDeal buy amount came back null, what was the fix"]:
        llm = FakeProvider(canned_text=f"ok [Ticket #75919]({URL})")
        d = Deps(retriever=FragmentRetriever(), llm=llm)
        turn = handle_turn(phrasing, Session.new(), Filters(),
                           "claude-haiku-4-5-20251001", deps=d)
        assert turn.kind == "answer"
        sent = llm.calls[-1]["messages"][-1]["content"]
        assert "buy amount came back null" in sent
        assert "re-added the field and redeployed" in sent
```

- [ ] **Step 2: Run it**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_orchestrator_tickets.py::test_same_ticket_question_is_consistent_across_rephrasings -v`
Expected: PASS (parent expansion already makes this hold; this test locks the behavior).

- [ ] **Step 3: Run the FULL kb_chatbot suite (regression gate)**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests -v`
Expected: PASS — all Phase 1 tests, all pre-existing tests, and all Phase 2 tests green. Fix any regression before committing (likely candidates: a pre-existing orchestrator test whose score is now `< OUT_OF_SCOPE_FLOOR`, or a prompt test pinning old rule-7 text — both are addressed in Tasks 5 and 8, but re-confirm here).

- [ ] **Step 4: Commit**

```bash
git add Dev/kb_chatbot/tests/test_orchestrator_tickets.py
git commit -m "test(v2.9.1): ticket-answer consistency across rephrasings (alpha regression guard)"
```

---

## Self-Review

**Spec coverage (Phase 2 = spec §6.2, §6.5b, §6.7a/b/e/f/g):**
- §6.7(a) parent-document reassembly → Tasks 1-2. ✓
- §6.7(b) raise answer cap → Task 3. ✓
- §6.5(b) output-side scrub → Task 4. ✓
- §6.2 3-tier out-of-scope + rewrite gating → Task 5. ✓
- §6.7(e) image link-note → Task 6. ✓
- §6.7(f) KB-alongside → Task 7. ✓
- §6.7(g) expert prompt → Task 8. ✓
- §6.7(d) reliability/determinism → Tasks 2 + 9 (parent expansion stabilises; test locks it). ✓
- **Deferred:** out-of-scope/confidence threshold *tuning* on the golden set — `OUT_OF_SCOPE_FLOOR=0.02` is a defensible default; final calibration is a Phase 4 verification step against the live golden set (the behavior tests here inject scores relative to the constants, so they hold at any calibrated value). The §6.1 Codex token work is Phase 3. The Learn-Mode KDF / rendering regression test / branding / version / reindex are Phase 4.

**Placeholder scan:** none — every step has real code/commands/expected output. The two "inspect the existing test and update it" steps (Task 5 Step 4, Task 8 Step 1) name the exact tests, the exact assertion to change, and why.

**Type consistency:** `assemble_ticket(list[Chunk]) -> Chunk` (Task 1) is consumed by `_expand_ticket_chunks` (Task 2); `config.ANSWER_MAX_TOKENS` (Task 3), `config.OUT_OF_SCOPE_FLOOR` + `OUT_OF_SCOPE_MESSAGE` (Task 5), `scrub_answer` (Task 4), `IMAGE_NOTE_TEMPLATE` (Task 6), `_ensure_kb_alongside` (Task 7) are all defined where first introduced and referenced consistently. `FakeProvider.calls[-1]["messages"]` is guaranteed by Task 2 Step 3a. The pipeline order in `handle_turn` is: retrieve → (rewrite if score≥OUT_OF_SCOPE_FLOOR) → augment/carry → clarify gate → `_expand_ticket_chunks` → `_ensure_kb_alongside` → build_messages → llm.chat(max_tokens=ANSWER_MAX_TOKENS) → scrub_answer → validate → footer → image-note.

**Risk note for the implementer:** Task 5 changes the abstain-path behavior for low-score queries; the two pre-existing orchestrator tests that assumed `ABSTAIN_MESSAGE`/suggestions at score `0.0` are updated in Task 5 Step 4 — run the full orchestrator file after Task 5, not just the new file.
