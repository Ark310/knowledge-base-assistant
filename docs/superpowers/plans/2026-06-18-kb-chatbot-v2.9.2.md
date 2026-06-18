# KB Chatbot v2.9.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development for the deterministic tasks (1-11); Task 12 (reindex+build) has human-checkpoint steps — do NOT auto-complete. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the bot feel like a chatbot that *knows the whole ticket pool + KB* (not search) — bridge old↔new tickets with recency, synthesize across the pool, stop the redundant clarification/context-loss — plus the FormFlow taxonomy and the chat-scroll/UI fixes.

**Architecture:** Answer-layer changes in `chat/orchestrator.py` + `prompt.py` (clarification bridging, broaden/balance/cross-ticket retrieval, synthesis/recency prompt), data-layer in `ticket_ingest.py` + `config.py` (recency date, product normalization, FormFlow) requiring a reindex, and `gui.py` UI fixes. Reuses the existing embed+rerank pipeline; no new models/providers.

**Tech Stack:** Python 3, pytest, PySide6. Tests run with `scraper/venv/Scripts/python.exe -m pytest` from the repo root.

## Global Constraints

- **Accuracy never sacrificed for breadth:** every factual claim keeps its `[Ticket #N](url)`/`[KB title](url)` citation; the bot still abstains when the answer isn't in CONTEXT (`citations.validate` + the CONTEXT-only rule are unchanged).
- **FormFlow** = first-class forms product; canonical slug **`formflow`**, display **"FormFlow"**; "FormFlow"/"FormFlow"/"FormFlow" are synonyms → `formflow`; **SalesHub stays separate**. Label "FormFlow" for the standalone product, "FormFlow" for the TradeDesk/embedded version (prompt rule).
- **Old↔new:** aggregate occurrences + **prefer the most recent ticket's fix** (surface dates).
- **Continuity-carry & ticket-ID pin are OUT** (already fixed in v2.9.1 — verified by replay); don't regress them.
- **Reindex required** (ticket chunk metadata changes) → bump `CHUNK_SCHEMA_VERSION`.
- **Test runner:** `scraper/venv/Scripts/python.exe -m pytest <path> -v` from repo root; imports `from Dev.kb_chatbot...`.
- **Commit after each task.** Branch `feat/kb-chatbot-v2.9.2` (spec committed at `5cce962`).

---

### Task 1: FormFlow taxonomy + product helpers — `config.py`

**Files:** Modify `Dev/kb_chatbot/config.py`; Test: `Dev/kb_chatbot/tests/test_config_providers.py`

**Interfaces:**
- Produces: `PRODUCTS` includes `"formflow"`; `PRODUCT_DISPLAY["formflow"]="FormFlow"`; `resolve_product(name)->Optional[str]` (synonym→slug); `normalize_ticket_product(raw)->str` (raw Project→slug). Consumed by orchestrator (Task 6) + ticket_ingest (Task 2).

- [ ] **Step 1: Write the failing tests**

Append to `Dev/kb_chatbot/tests/test_config_providers.py`:
```python
def test_formflow_is_first_class_product():
    from Dev.kb_chatbot import config
    assert "formflow" in config.PRODUCTS
    assert config.PRODUCT_DISPLAY["formflow"] == "FormFlow"
    assert "saleshub" in config.PRODUCTS  # stays separate

def test_resolve_product_synonyms():
    from Dev.kb_chatbot import config
    for s in ("FormFlow", "formflow", "formflow", "FormFlow"):
        assert config.resolve_product(s) == "formflow"
    assert config.resolve_product("SalesHub") == "saleshub"
    assert config.resolve_product("nonsense") is None

def test_normalize_ticket_product():
    from Dev.kb_chatbot import config
    assert config.normalize_ticket_product("FormFlow") == "formflow"
    assert config.normalize_ticket_product("SalesHub") == "saleshub"
    assert config.normalize_ticket_product("TD Client Server") == "tradedesk"
    assert config.normalize_ticket_product("TD Web Portal V4.0") == "web4"
    assert config.normalize_ticket_product("Rest API") == "api"
    assert config.normalize_ticket_product("Totally Unknown") == "other"
```

- [ ] **Step 2: Run → fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_config_providers.py -k "formflow or resolve_product or normalize_ticket" -v`
Expected: FAIL (no `formflow`, no helpers).

- [ ] **Step 3: Implement**

In `Dev/kb_chatbot/config.py`, change `PRODUCTS`/`PRODUCT_DISPLAY` and add the helpers (the `Optional` import already exists at the top):
```python
PRODUCTS = ("api", "tradedesk", "saleshub", "formflow", "web2", "web4", "other")
PRODUCT_DISPLAY = {
    "api": "API", "tradedesk": "TradeDesk", "saleshub": "SalesHub",
    "formflow": "FormFlow", "web2": "Web2", "web4": "Web4", "other": "Other",
}

# FormFlow (standalone) == FormFlow (legacy, embedded in TradeDesk/others) — one
# forms product. SalesHub is separate.
_PRODUCT_SYNONYMS = {
    "formflow": "formflow", "formflow": "formflow",
    "formflow": "formflow", "formflow": "formflow",
    "saleshub": "saleshub", "saleshub": "saleshub",
    "tradedesk": "tradedesk", "td": "tradedesk",
    "web2": "web2", "web4": "web4", "api": "api", "other": "other",
}

def resolve_product(name: str) -> Optional[str]:
    """Map a product name/synonym typed by a user to a canonical slug, or None."""
    return _PRODUCT_SYNONYMS.get((name or "").strip().lower())

# Raw ticket "Project" value -> canonical product slug (tickets store rich Project
# names that don't match KB slugs). Unknown -> "other"; raw value kept separately.
_TICKET_PROJECT_MAP = {
    "td client server": "tradedesk", "business modeling": "tradedesk",
    "td web api": "api", "rest api": "api",
    "td web portal v4.0": "web4",
    "td web portal v2.0": "web2", "td web portal v1": "web2",
    "formflow": "formflow", "saleshub": "saleshub",
}

def normalize_ticket_product(raw: str) -> str:
    return _TICKET_PROJECT_MAP.get((raw or "").strip().lower(), "other")
```

- [ ] **Step 4: Run → pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_config_providers.py -v`
Expected: PASS (new + existing; adding a product doesn't change `default_provider`/aliases).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/tests/test_config_providers.py
git commit -m "feat(v2.9.2): FormFlow first-class product + resolve_product / normalize_ticket_product helpers"
```

---

### Task 2: Ticket recency date + product normalization — `ticket_ingest.py`

**Files:** Modify `Dev/kb_chatbot/ticket_ingest.py` (`build_ticket_chunks`, add `_parse_created_at`); Test: `Dev/kb_chatbot/tests/test_ticket_ingest.py`

**Interfaces:**
- Consumes: `config.normalize_ticket_product` (Task 1).
- Produces: ticket chunk metadata gains `created_at` (ISO `YYYY-MM-DD` or ""), `project` (raw Project string), and `product` is now the **normalized slug**; chunk-0 text carries a `Date: <YYYY-MM-DD>` line. Consumed by the answer layer (Tasks 8-9) + display.

- [ ] **Step 1: Write the failing tests**

Append to `Dev/kb_chatbot/tests/test_ticket_ingest.py`:
```python
from Dev.kb_chatbot.ticket_ingest import _parse_created_at

def test_parse_created_at_formats():
    assert _parse_created_at("2024-08-22 6:37 AM") == "2024-08-22"
    assert _parse_created_at("2024-08-22") == "2024-08-22"
    assert _parse_created_at("") == ""
    assert _parse_created_at("garbage") == ""

def test_chunk_has_recency_and_normalized_product(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "email", "header": "", "body": "It broke."},
        {"type": "comment", "author": "a.user", "header": "", "body": "Fixed it."},
    ], product="FormFlow", created_at="2024-08-22 6:37 AM")
    chunks = build_ticket_chunks(data, p)
    m = chunks[0].metadata
    assert m["product"] == "formflow"       # normalized
    assert m["project"] == "FormFlow"      # raw kept
    assert m["created_at"] == "2024-08-22"
    assert "Date: 2024-08-22" in chunks[0].text
```
(The shared `_ticket` helper already exists and forwards `**over` into the ticket dict, so `product=`/`created_at=` kwargs work.)

- [ ] **Step 2: Run → fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_ingest.py -k "created_at or recency_and_normalized" -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `Dev/kb_chatbot/ticket_ingest.py`, add the import `from Dev.kb_chatbot import config` if not present, and a date parser near the top:
```python
from datetime import datetime

def _parse_created_at(raw: str) -> str:
    """Parse a ticket created_at like '2024-08-22 6:37 AM' to an ISO date 'YYYY-MM-DD'.
    Returns '' on empty/unparseable input (never raises)."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # last resort: leading YYYY-MM-DD token
    import re as _re
    m = _re.match(r"\d{4}-\d{2}-\d{2}", raw)
    return m.group(0) if m else ""
```
In `build_ticket_chunks`, change the `product` line and add date + raw project. Replace:
```python
    product = data.get("product", "") or "tickets"
```
with:
```python
    raw_project = (data.get("product", "") or "").strip()
    product = config.normalize_ticket_product(raw_project)
    created_at = _parse_created_at(data.get("created_at", ""))
```
Add the date to the chunk-0 header — change the chunk-0 header block:
```python
        text = title_line
        if idx == 0:
            if created_at:
                text += f"\nDate: {created_at}"
            if header:
                text += "\n" + header
```
And add to the metadata dict:
```python
                "product": product,
                "project": raw_project,
                "created_at": created_at,
```
(Keep all other metadata keys.)

- [ ] **Step 4: Run → pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_ticket_ingest.py -v`
Expected: PASS (new + existing — existing tests that check `Problem:`/`Resolution:`/url still hold; `product` for the existing TD fixture becomes `tradedesk`, so update any existing assertion that expected the raw "TD …" value to expect the slug, or assert on `project` for the raw value).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/ticket_ingest.py Dev/kb_chatbot/tests/test_ticket_ingest.py
git commit -m "feat(v2.9.2): ticket chunk recency date (created_at + Date line) + normalized product slug (raw kept as project)"
```

---

### Task 3: Bump CHUNK_SCHEMA_VERSION — `ingest.py`

**Files:** Modify `Dev/kb_chatbot/ingest.py`; Test: `Dev/kb_chatbot/tests/test_ingest.py`

- [ ] **Step 1: Failing test** — append:
```python
def test_chunk_schema_version_is_4():
    from Dev.kb_chatbot.ingest import CHUNK_SCHEMA_VERSION
    assert CHUNK_SCHEMA_VERSION == 4
```
- [ ] **Step 2: Run → fail** (`-k schema_version_is_4`) — currently 3.
- [ ] **Step 3:** set `CHUNK_SCHEMA_VERSION = 4` in `ingest.py`.
- [ ] **Step 4: Run → pass** (`Dev/kb_chatbot/tests/test_ingest.py -v`).
- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/ingest.py Dev/kb_chatbot/tests/test_ingest.py
git commit -m "chore(v2.9.2): bump CHUNK_SCHEMA_VERSION to 4 (ticket recency + product normalization)"
```

---

### Task 4: Clarification bridging + anti-re-clarify — `chat/orchestrator.py`

**Files:** Modify `Dev/kb_chatbot/chat/orchestrator.py`; Test: `Dev/kb_chatbot/tests/test_orchestrator_clarify.py` (new)

**Interfaces:**
- Produces: after a clarification is answered, the LLM message carries a bridge note restating the original question; both clarify gates are suppressed for that turn.

- [ ] **Step 1: Write the failing tests**

Create `Dev/kb_chatbot/tests/test_orchestrator_clarify.py`:
```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps, CLARIFY_BRIDGE_NOTE
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.retriever import Filters, RetrievalResult
from Dev.kb_chatbot.llm.fake_provider import FakeProvider


def _kbchunk(title, url):
    return Chunk(id="k1", text="content",
                 metadata={"product": "tradedesk", "category": "dealing",
                           "title": title, "url": url})


class _R:
    """Confident retrieval so we reach the answer branch."""
    def retrieve(self, query, filters):
        return RetrievalResult(chunks=[_kbchunk("Drawdown", "https://help.contoso.example/dd")],
                               rerank_top_score=0.9)
    def get_by_ids(self, ids): return []
    def get_by_ticket_ids(self, tids): return []
    def retrieve_quick(self, query, limit=10): return []
    def suggest(self, query, top_k=5): return []


def test_answer_after_clarification_fuses_original_and_does_not_reclarify():
    llm = FakeProvider(canned_text="ok [Drawdown](https://help.contoso.example/dd)")
    d = Deps(retriever=_R(), llm=llm)
    s = Session.new()
    s.add_user("drawdown margin duplication on a full multi-line forward drawdown")
    s.add(__import__("Dev.kb_chatbot.chat.session", fromlist=["Turn"]).Turn(
        role="assistant", kind="clarification", content="Which product? TradeDesk / Web2?"))
    turn = handle_turn("TD Client Server", s, Filters(),
                       "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "answer"                       # did NOT re-clarify
    sent = llm.calls[-1]["messages"][-1]["content"]
    assert "drawdown margin duplication" in sent       # original question fused in
    assert "do not ask another clarifying question" in sent.lower()
```

- [ ] **Step 2: Run → fail** (`CLARIFY_BRIDGE_NOTE` undefined).

- [ ] **Step 3: Implement**

In `orchestrator.py`, add the constant near `DRIFT_NOTE`:
```python
CLARIFY_BRIDGE_NOTE = (
    "\n\n[CLARIFICATION ANSWERED — the user's original question was: \"{orig}\". "
    "They have now specified: \"{reply}\". Answer that original question directly "
    "using CONTEXT. Do NOT ask another clarifying question.]"
)
```
In `handle_turn`, right after computing `retrieval_query, extracted_product = _build_retrieval_query(...)` (before `session.add_user`), capture the clarification state:
```python
    answering_clarification = session.last_assistant_kind() == "clarification"
    original_q = session.last_user_question() if answering_clarification else ""
```
Suppress both clarify gates: change the answer-branch guard (currently `if not skip_clarify and not (...):`) to also require `not answering_clarification`:
```python
        if not skip_clarify and not answering_clarification and not (filters.product or _mentions_product(user_msg) or _recent_product_in_history(session)):
```
and the abstain-branch clarifier guard (currently `if result.rerank_top_score > config.CLARIFY_SCORE_FLOOR and not (...):`) to add `and not answering_clarification`.
Build the bridge into the LLM message: change the `user_msg=user_msg + drift_note` argument of `build_messages(...)` to use a fused message:
```python
            llm_user_msg = user_msg + drift_note
            if answering_clarification and original_q:
                llm_user_msg += CLARIFY_BRIDGE_NOTE.format(orig=original_q, reply=user_msg)
            messages = build_messages(
                context_chunks=result.chunks,
                history=history,
                user_msg=llm_user_msg,
                attachments=deps.attachments or [],
            )
```

- [ ] **Step 4: Run → pass** (`test_orchestrator_clarify.py` + `test_orchestrator.py` + `test_orchestrator_tickets.py` + `test_orchestrator_scope.py` all green — the new guard only suppresses clarification *after* a clarification, so existing first-clarify tests are unaffected).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_orchestrator_clarify.py
git commit -m "feat(v2.9.2): bridge original question after a clarification + suppress re-clarification (fixes CONV A)"
```

---

### Task 5: Prompt rules — clarify-once, FormFlow labeling, synthesis+recency, proactive — `prompt.py`

**Files:** Modify `Dev/kb_chatbot/prompt.py` (`SYSTEM_PROMPT`); Test: `Dev/kb_chatbot/tests/test_prompt.py`

- [ ] **Step 1: Update the prompt test** — in `test_prompt.py`, replace the body of `test_system_prompt_locked_text_v23` with invariant + new-rule assertions:
```python
def test_system_prompt_locked_text_v23():
    p = build_system_prompt()
    assert "only use facts from the CONTEXT block" in p
    assert "I don't have enough information in the knowledge base" in p
    assert "[Article Title](url)" in p
    assert "Root cause" in p and "Sources:" in p
    # v2.9.2
    assert "FormFlow" in p
    assert "do not ask another clarifying question" in p.lower()
    assert "most recent" in p.lower()
```
- [ ] **Step 2: Run → fail** (`-k system_prompt_locked_text`) — "FormFlow" not present.

- [ ] **Step 3: Edit `SYSTEM_PROMPT`.**
  - Preamble: change the product list to "…for TradeDesk, Web2, Web4, SalesHub, **FormFlow**, and the API."
  - Replace rule 4 with: *"4. Ask **at most one** clarifying question per topic, and only when the answer genuinely **differs** between candidates (if the same answer applies across products/topics, answer it and note where it also applies). If your previous message in this conversation was a clarifying question and the user has now responded, you **MUST** answer using the full conversation — do **not** ask another clarifying question."*
  - Append two rules after rule 11:
    *"12. Products: FormFlow is Contoso's standalone forms product; FormFlow is the older forms version embedded in TradeDesk and other apps — treat them as the same product. Refer to it as **FormFlow** when the user asks about the standalone product, and **FormFlow** when discussing the TradeDesk/embedded version. SalesHub is a separate product."*
    *"13. Be a pool-aware expert. When answering an issue/error, synthesize across ALL relevant tickets and KB in CONTEXT: give the root cause + resolution, **prefer the most recent ticket's fix as authoritative** (use the `Date:` line; note older occurrences), and add a brief synthesis — how many tickets, which clients, the date range, and the most recent [Ticket #<id>](url). You MAY add one short proactive line offering the closest related issue or a likely next step. Never fabricate; every claim keeps its citation; abstain if it isn't in CONTEXT."*

- [ ] **Step 4: Run → pass** (`test_prompt.py -v`; update any other assertion pinning the old rule-4 text).

- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/prompt.py Dev/kb_chatbot/tests/test_prompt.py
git commit -m "feat(v2.9.2): prompt — clarify-once/anti-re-clarify, FormFlow labeling, pool-aware synthesis + recency + proactive"
```

---

### Task 6: FormFlow in scope/clarifier copy + synonym-aware product detection — `chat/orchestrator.py`

**Files:** Modify `Dev/kb_chatbot/chat/orchestrator.py`; Test: `Dev/kb_chatbot/tests/test_orchestrator_scope.py`

**Interfaces:** Consumes `config.resolve_product`.

- [ ] **Step 1: Failing tests** — append to `test_orchestrator_scope.py`:
```python
def test_scope_and_abstain_mention_aml_forms():
    from Dev.kb_chatbot import orchestrator as o
    assert "FormFlow" in o.OUT_OF_SCOPE_MESSAGE
    assert "FormFlow" in o.ABSTAIN_MESSAGE

def test_mentions_product_recognizes_aml_synonyms():
    from Dev.kb_chatbot.chat.orchestrator import _mentions_product, _extract_single_product
    assert _mentions_product("how do I open an FormFlow form")
    assert _extract_single_product("question about formflow") == "formflow"
```
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement.**
  - Add "FormFlow" to `OUT_OF_SCOPE_MESSAGE`, `ABSTAIN_MESSAGE`, `SHORT_QUERY_CLARIFICATION`, and the `_default_clarifier` fallback list (e.g. "API, TradeDesk, SalesHub, FormFlow, Web2, Web4, or Other").
  - Make `_extract_single_product` and `_mentions_product` synonym-aware via `config.resolve_product` over multi-word names. Replace `_extract_single_product` body:
```python
def _extract_single_product(text: str) -> Optional[str]:
    low = text.lower()
    found = set()
    # multi-word synonyms first (e.g. "formflow", "saleshub")
    for name in ("formflow", "formflow", "formflow", "saleshub", "saleshub",
                 "tradedesk", "web2", "web4", "api", "other"):
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            slug = config.resolve_product(name)
            if slug:
                found.add(slug)
    return next(iter(found)) if len(found) == 1 else None
```
and `_mentions_product`:
```python
def _mentions_product(text: str) -> bool:
    low = text.lower()
    if any(re.search(r"\b" + re.escape(p) + r"\b", low) for p in config.PRODUCTS):
        return True
    return any(syn in low for syn in ("formflow", "formflow", "saleshub"))
```
- [ ] **Step 4: Run → pass** (`test_orchestrator_scope.py` + `test_orchestrator.py` green).
- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_orchestrator_scope.py
git commit -m "feat(v2.9.2): FormFlow in scope/abstain/clarifier copy + synonym-aware product detection"
```

---

### Task 7: Broaden retrieval for error questions — `retriever.py`, `chat/orchestrator.py`, `config.py`

**Files:** Modify `Dev/kb_chatbot/retriever.py` (`retrieve` gains `top_k_rerank` override), `config.py` (`TOP_K_RERANK_ERROR`), `chat/orchestrator.py` (`_looks_like_error` + pass the override); Test: `Dev/kb_chatbot/tests/test_retriever.py`, `test_orchestrator_tickets.py`

**Interfaces:** Produces `orchestrator._looks_like_error(query)->bool`; `Retriever.retrieve(query, filters, top_k_rerank=None)`; `config.TOP_K_RERANK_ERROR=14`.

- [ ] **Step 1: Failing tests**

Append to `Dev/kb_chatbot/tests/test_retriever.py`:
```python
def test_looks_like_error():
    from Dev.kb_chatbot.chat.orchestrator import _looks_like_error
    assert _looks_like_error("GetWebDeal returns a null buy amount error")
    assert _looks_like_error("the drawdown margin is duplicated incorrectly")
    assert not _looks_like_error("how do I book a spot deal")
```
Append to `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`:
```python
def test_error_query_uses_wider_topk(monkeypatch):
    from Dev.kb_chatbot import config
    from Dev.kb_chatbot.chat import orchestrator as o
    captured = {}
    class R2(FragmentRetriever):
        def retrieve(self, query, filters, top_k_rerank=None):
            captured["k"] = top_k_rerank
            return RetrievalResult(chunks=[_frag(0, "Problem: x")], rerank_top_score=0.9)
    llm = FakeProvider(canned_text=f"ok [Ticket #75919]({URL})")
    handle_turn("there is an error: buy amount is null and failing",
                Session.new(), Filters(), "claude-haiku-4-5-20251001",
                deps=Deps(retriever=R2(), llm=llm))
    assert captured["k"] == config.TOP_K_RERANK_ERROR
```

- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement.**
  - `config.py`: add `TOP_K_RERANK_ERROR = 14` near `TOP_K_RERANK`.
  - `retriever.py`: change `def retrieve(self, query, filters):` to `def retrieve(self, query, filters, top_k_rerank=None):` and inside use `k = top_k_rerank or self.top_k_rerank` wherever `self.top_k_rerank` slices the reranked list (`top = scored[: k]`).
  - `orchestrator.py`: add near the other helpers:
```python
_ERROR_RE = re.compile(
    r"\b(error|errors|issue|issues|fail(?:s|ed|ing|ure)?|null|exception|crash(?:e[ds])?|"
    r"bug|broken|wrong|incorrect|discrepan\w*|duplicat\w*|missing|not working|doesn'?t|"
    r"cannot|can'?t|unable)\b", re.IGNORECASE)

def _looks_like_error(query: str) -> bool:
    return bool(_ERROR_RE.search(query or ""))
```
  and in `handle_turn`, compute `err_q = _looks_like_error(retrieval_query)` after building `retrieval_query`, and pass the override on BOTH `deps.retriever.retrieve(...)` calls:
```python
    result = deps.retriever.retrieve(retrieval_query, filters,
                                     top_k_rerank=(config.TOP_K_RERANK_ERROR if err_q else None))
```
(and the same in the rewrite-escalation re-retrieve).

- [ ] **Step 4: Run → pass** (`test_retriever.py` + `test_orchestrator*.py` green; the default-None path keeps existing tests' behavior).
- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/retriever.py Dev/kb_chatbot/config.py Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_retriever.py Dev/kb_chatbot/tests/test_orchestrator_tickets.py
git commit -m "feat(v2.9.2): widen rerank top-K for error/issue questions"
```

---

### Task 8: Balanced sources — attach tickets when KB-dominated — `chat/orchestrator.py`

**Files:** Modify `Dev/kb_chatbot/chat/orchestrator.py`; Test: `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`

**Interfaces:** Produces `_ensure_tickets_alongside(query, chunks, retriever)`; wired after `_ensure_kb_alongside`.

- [ ] **Step 1: Failing test** — append to `test_orchestrator_tickets.py`:
```python
def test_error_query_attaches_ticket_when_kb_only():
    kb = Chunk(id="kb1", text="How-toForms", metadata={"product": "formflow",
               "category": "how_to", "title": "FormFlow How-To",
               "url": "https://help.contoso.example/aml"})
    tk = _frag(0, "Problem: form submit fails")
    class R(FragmentRetriever):
        def retrieve(self, query, filters, top_k_rerank=None):
            return RetrievalResult(chunks=[kb], rerank_top_score=0.9)  # KB only
        def retrieve_quick(self, query, limit=10):
            return [tk]   # a ticket is available
    llm = FakeProvider(canned_text="ok")
    handle_turn("form submit fails with an error",
                Session.new(), Filters(), "claude-haiku-4-5-20251001",
                deps=Deps(retriever=R(), llm=llm))
    sent = llm.calls[-1]["messages"][-1]["content"]
    assert "Ticket #75919" in sent   # a ticket got attached alongside the KB
```
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — add after `_ensure_kb_alongside`:
```python
def _ensure_tickets_alongside(query: str, chunks: list[Chunk], retriever) -> list[Chunk]:
    """If the context is KB-only for an error question, attach the best ticket
    (errors live on tickets too). Best-effort; reuses retrieve_quick."""
    has_kb = any(c.metadata.get("kind") != "ticket" for c in chunks)
    has_ticket = any(c.metadata.get("kind") == "ticket" for c in chunks)
    if not has_kb or has_ticket:
        return chunks
    seen = {c.id for c in chunks}
    for cand in retriever.retrieve_quick(query, limit=10):
        if cand.metadata.get("kind") == "ticket" and cand.id not in seen:
            return [*chunks, cand]
    return chunks
```
and wire it in `handle_turn`, gated on error queries, right after the `_ensure_kb_alongside` line:
```python
        result.chunks = _ensure_kb_alongside(retrieval_query, result.chunks, deps.retriever)
        if _looks_like_error(retrieval_query):
            result.chunks = _ensure_tickets_alongside(retrieval_query, result.chunks, deps.retriever)
            result.chunks = _expand_ticket_chunks(result.chunks, deps.retriever)  # assemble any newly attached ticket
```
- [ ] **Step 4: Run → pass** (`test_orchestrator_tickets.py` + `test_orchestrator.py` green; non-error/KB-present paths unchanged).
- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_orchestrator_tickets.py
git commit -m "feat(v2.9.2): attach a ticket alongside KB for error questions (balanced sources)"
```

---

### Task 9: Cross-ticket same-error surfacing incl. most recent — `chat/orchestrator.py`

**Files:** Modify `Dev/kb_chatbot/chat/orchestrator.py`; Test: `Dev/kb_chatbot/tests/test_orchestrator_tickets.py`

**Interfaces:** Produces `_add_related_tickets(chunks, retriever, *, limit=2)` — for the first ticket in context, merge up to `limit` additional distinct same-error tickets (via `retrieve_quick` on that ticket's title, `kind=="ticket"`, dedup by `ticket_id`), preferring the most recent by `created_at`. Wired in the error path.

- [ ] **Step 1: Failing test** — append to `test_orchestrator_tickets.py`:
```python
def test_related_tickets_merged_and_recent_first():
    primary = _frag(0, "Problem: margin duplicated")  # ticket_id 75919
    older = Chunk(id="ti_old", text="Ticket #54000 — margin dup\nDate: 2021-01-01\n\nProblem: dup",
                  metadata={"kind": "ticket", "ticket_id": "54000", "title": "Ticket #54000",
                            "url": "u54000", "created_at": "2021-01-01", "chunk_index": 0})
    newer = Chunk(id="ti_new", text="Ticket #61000 — margin dup\nDate: 2024-05-05\n\nProblem: dup",
                  metadata={"kind": "ticket", "ticket_id": "61000", "title": "Ticket #61000",
                            "url": "u61000", "created_at": "2024-05-05", "chunk_index": 0})
    class R(FragmentRetriever):
        def retrieve(self, query, filters, top_k_rerank=None):
            return RetrievalResult(chunks=[primary], rerank_top_score=0.9)
        def retrieve_quick(self, query, limit=10):
            return [older, newer]
    llm = FakeProvider(canned_text=f"ok [Ticket #75919]({URL})")
    handle_turn("margin duplication error on drawdown",
                Session.new(), Filters(), "claude-haiku-4-5-20251001",
                deps=Deps(retriever=R(), llm=llm))
    sent = llm.calls[-1]["messages"][-1]["content"]
    assert "Ticket #54000" in sent and "Ticket #61000" in sent  # both related merged
    # most-recent appears before older in the assembled context
    assert sent.index("61000") < sent.index("54000")
```
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — add:
```python
def _add_related_tickets(chunks: list[Chunk], retriever, *, limit: int = 2) -> list[Chunk]:
    """Surface additional distinct tickets covering the same error as the first ticket
    in context — bridging old↔new. Recent-first by created_at; deduped by ticket_id."""
    tickets = [c for c in chunks if c.metadata.get("kind") == "ticket"]
    if not tickets:
        return chunks
    seed = tickets[0]
    have = {c.metadata.get("ticket_id") for c in tickets}
    cands = [c for c in retriever.retrieve_quick(seed.metadata.get("title", "") + " " + seed.text[:200], limit=12)
             if c.metadata.get("kind") == "ticket" and c.metadata.get("ticket_id") not in have]
    # dedup by ticket_id, prefer most recent
    by_id: dict = {}
    for c in cands:
        tid = c.metadata.get("ticket_id")
        if tid and tid not in by_id:
            by_id[tid] = c
    extra = sorted(by_id.values(), key=lambda c: c.metadata.get("created_at", ""), reverse=True)[:limit]
    return [*chunks, *extra]
```
Wire it in the error path right after `_ensure_tickets_alongside`/expansion:
```python
        if _looks_like_error(retrieval_query):
            result.chunks = _ensure_tickets_alongside(retrieval_query, result.chunks, deps.retriever)
            result.chunks = _expand_ticket_chunks(result.chunks, deps.retriever)
            result.chunks = _add_related_tickets(result.chunks, deps.retriever)
            result.chunks = _expand_ticket_chunks(result.chunks, deps.retriever)  # assemble related
```
- [ ] **Step 4: Run → pass** (full `test_orchestrator*.py` green; non-error paths untouched).
- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_orchestrator_tickets.py
git commit -m "feat(v2.9.2): cross-ticket same-error surfacing (bridge old<->new, recent-first)"
```

---

### Task 10: UI — scroll fix, deferred nits, light polish — `gui.py`

**Files:** Modify `Dev/kb_chatbot/gui.py`; Test: `Dev/kb_chatbot/tests/test_render.py`

- [ ] **Step 1: Failing test** — append to `test_render.py`:
```python
def test_append_scrolls_to_bottom(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QTextCursor
    QApplication.instance() or QApplication([])
    from Dev.kb_chatbot import gui
    calls = {"end": 0, "max": 0}
    class FakeSB:
        def maximum(self): return 999
        def setValue(self, v): calls["max"] = v
    class FakeView:
        def clear(self): pass
        def append(self, b): pass
        def moveCursor(self, c):
            if c == QTextCursor.End: calls["end"] += 1
        def verticalScrollBar(self): return FakeSB()
        def ensureCursorVisible(self): pass
    mw = gui.MainWindow.__new__(gui.MainWindow)
    mw.chat_view = FakeView(); mw._welcome_showing = False
    gui.MainWindow._append(mw, "ai", "hi", "#000", "AI:")
    assert calls["end"] == 1 and calls["max"] == 999   # cursor to End + scrolled to bottom
```
- [ ] **Step 2: Run → fail** (current `_append` calls `ensureCursorVisible`, not moveCursor/scrollbar).
- [ ] **Step 3: Implement.**
  - In `_append`, replace `self.chat_view.ensureCursorVisible()` with:
```python
        self.chat_view.moveCursor(QTextCursor.End)
        sb = self.chat_view.verticalScrollBar()
        sb.setValue(sb.maximum())
```
  (`QTextCursor` is already imported at the top of gui.py.)
  - **AboutDialog nit:** remove the dead `bb.accepted.connect(self.accept)` line (Close-only box never emits `accepted`).
  - **Welcome-hint width nit:** in `_welcome_html`, wrap the hint text in a `<div style="max-width:360px;margin:0 auto;">…</div>`.
  - **Light polish:** in `_build_message_html`, bump message padding/line-height modestly (e.g. `padding:8px 12px; line-height:1.45;`) — cosmetic only; keep the escape-then-linkify logic intact (the existing XSS tests must still pass).
- [ ] **Step 4: Run → pass** (`test_render.py` + `test_assets.py` green; `import Dev.kb_chatbot.gui` clean).
- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/gui.py Dev/kb_chatbot/tests/test_render.py
git commit -m "fix(v2.9.2): chat auto-scrolls to latest (no more jump-to-top) + About/welcome nits + light polish"
```

---

### Task 11: Version bump to 2.9.2 — `config.py`, build script

**Files:** Modify `config.py`, `build_chatbot_exe.bat`; Test: `test_version.py`

- [ ] **Step 1: Failing test** — change `test_version.py` assertion to `assert config.APP_VERSION == "2.9.2"` (rename to `test_app_version_is_2_9_2`).
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3:** `config.APP_VERSION = "2.9.2"`; in `build_chatbot_exe.bat` change `--workpath build_v291` → `--workpath build_v292` and the echoed artifact path to `…-v2.9.2…`.
- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit**
```bash
git add Dev/kb_chatbot/config.py build_chatbot_exe.bat Dev/kb_chatbot/tests/test_version.py
git commit -m "chore(v2.9.2): bump APP_VERSION to 2.9.2 + build workpath"
```

---

### Task 12: Reindex + smoke + build (GATED — user OK before compile)

**This task is NOT auto-completed. The exe compile requires a passing smoke test + explicit user confirmation.**

- [ ] **Step 1: Full suite green** — `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests -v` → all pass.
- [ ] **Step 2: Reindex** — `scraper/venv/Scripts/python.exe _v291_reindex.py` (CHUNK_SCHEMA_VERSION=4 forces full re-embed); confirm ticket chunks carry normalized `product` + raw `project` + `created_at`; run `_v291_secret_probe.py` → `leaks=0`.
- [ ] **Step 3: Source smoke (controller-run, both providers)** — replay the alpha conversations + new checks via a throwaway `_v292_smoke.py`: CONV A → no double-clarify / no forced repeat; an error question → tickets + KB + ≥1 related ticket + **a recency line / most-recent ticket cited**; an "FormFlow" question → recognized + labeled FormFlow (and FormFlow in an TradeDesk context); SalesHub stays separate. Record results.
- [ ] **Step 4: HUMAN CHECKPOINT** — present smoke results; compile only after explicit approval.
- [ ] **Step 5: Build** — `build_chatbot_exe.bat` (fresh `--workpath build_v292`); re-copy the prebuilt index into `dist/ContosoKBChatbot-v2.9.2/chatbot_state/chroma/`; launch the exe; confirm version 2.9.2, branding, a synthesized error answer with recency.
- [ ] **Step 6: Commit** any build-doc updates.

---

## Self-Review

**Spec coverage:** §6.1 clarification/bridging → Tasks 4-5; §6.2 referencing (recency, broaden, balance, cross-ticket, synthesis) → Tasks 2,5,7,8,9; §6.3 FormFlow taxonomy → Tasks 1,2,5,6; §6.4 UI → Task 10; §6.5 version/reindex/build → Tasks 3,11,12. ✓ Continuity-carry & ID-pin intentionally untouched (non-goal). ✓

**Placeholder scan:** none — every step has concrete code/commands/expected output. Threshold values (`TOP_K_RERANK_ERROR=14`, related-ticket `limit=2`) are defensible defaults; the behavior tests assert the *mechanism* (override passed, related tickets merged, recent-first), independent of the exact number; final values confirmed at the §6.2(e) golden tuning in Task 12 Step 3.

**Type consistency:** `config.resolve_product`/`normalize_ticket_product` (Task 1) consumed by Tasks 2,6; `_looks_like_error` (Task 7) reused in Tasks 8,9; `Retriever.retrieve(..., top_k_rerank=None)` (Task 7) used in orchestrator + must keep all existing `retrieve(q, f)` callers working (the new param is optional/defaulted); `_ensure_tickets_alongside`/`_add_related_tickets` (Tasks 8,9) wired in the error path after `_ensure_kb_alongside`; ticket metadata `created_at`/`project` (Task 2) consumed by Task 9's recency sort + the prompt's `Date:`-line rule (Task 5). `CHUNK_SCHEMA_VERSION=4` (Task 3) drives the Task 12 reindex.

**Risk note:** Task 2 changes the existing ticket fixture's `product` from raw "TD …" to the slug — re-run `test_ticket_ingest.py` fully and update any assertion that pinned the raw value (assert on `project` for raw). Task 7's `retrieve` signature change must be applied to the real `Retriever` and any FakeRetriever in tests that defines `retrieve(self, query, filters)` (add `top_k_rerank=None`).
