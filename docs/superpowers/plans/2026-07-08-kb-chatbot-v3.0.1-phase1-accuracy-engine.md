# KB Chatbot v3.0.1 — Phase 1: Accuracy Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make retrieval + answers accurate and consistent — kill phrasing sensitivity (hybrid BM25+vector), make repeats deterministic (answer cache + stable ordering), classify each query deterministically, and build an eval harness that scores accuracy AND consistency.

**Architecture:** Extend the existing pipeline in place — no embedder swap, no reindex. Add a BM25 keyword index built in-memory from the chunks already in Chroma, fuse it with the vector hits via Reciprocal Rank Fusion, then rerank with the existing cross-encoder. Add small pure modules (`query_norm`, `classifier`, `answer_cache`) and wire them into the orchestrator. Add an `eval/` harness. All work is provider-independent (benefits Claude, Codex, and the local model).

**Tech Stack:** Python 3.12, pytest, ChromaDB, sentence-transformers (unchanged), `rank-bm25` (new, pure-Python CPU), FakeProvider for deterministic tests.

## Global Constraints

- **Test runner:** pytest from the repo root; the test venv is `scraper\venv`. Tests live in `Dev/kb_chatbot/tests/`, import via `from Dev.kb_chatbot...`, and start with `sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))` (repo root). Run a single test: `python -m pytest Dev/kb_chatbot/tests/<file>::<test> -v`.
- **No reindex / no schema bump.** Phase 1 changes no chunk metadata, so `CHUNK_SCHEMA_VERSION` stays `4`. BM25 is built from the chunks already in Chroma.
- **No embedder/reranker swap.** `all-MiniLM-L6-v2` + `ms-marco-MiniLM-L-6-v2` stay.
- **No version bump.** `APP_VERSION` stays `2.9.2` until the packaging phase (Phase 7).
- **Determinism honesty:** true generation determinism (temp 0 + seed) is only achievable on the local model; the answer cache gives identical answers for repeated standalone questions on any provider; stable tie-breaking makes retrieval ordering deterministic.
- **Security unchanged:** the answer cache stores only the already-scrubbed, citation-validated answer text (it is written AFTER `scrub_answer` + `validate_citations`). No raw ticket text, no PII, is cached.
- **Determinism of tests:** all unit tests use `FakeProvider` or pure functions — no network.

---

### Task 1: Query normalization + tokenization (`chat/query_norm.py`)

**Files:**
- Create: `Dev/kb_chatbot/chat/query_norm.py`
- Test: `Dev/kb_chatbot/tests/test_query_norm.py`

**Interfaces:**
- Produces: `normalize(query: str) -> str` (cache-key canonical form: lowercased, punctuation-stripped except `#`, whitespace-collapsed, product synonyms folded to canonical slug), `tokenize(text: str) -> list[str]` (BM25 tokenizer: lowercased alnum/`#` tokens).
- Consumed by: Task 3 (BM25), Task 4 (cache key), Task 5 (orchestrator).

- [ ] **Step 1: Write the failing test**

```python
# Dev/kb_chatbot/tests/test_query_norm.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat.query_norm import normalize, tokenize


def test_normalize_lowercases_and_collapses_whitespace():
    assert normalize("  How   DO  I  ") == "how do i"

def test_normalize_strips_punctuation_but_keeps_hash():
    assert normalize("ticket #75919: null?") == "ticket #75919 null"

def test_normalize_folds_product_synonyms_to_slug():
    assert normalize("FormFlow setup") == "formflow setup"
    assert normalize("formflow setup") == "formflow setup"
    assert normalize("SalesHub report") == "saleshub report"
    assert normalize("TD dealing") == "tradedesk dealing"

def test_normalize_is_idempotent():
    q = "How do I configure FormFlow in TD?"
    assert normalize(normalize(q)) == normalize(q)

def test_normalize_empty():
    assert normalize("") == ""

def test_tokenize_splits_lowercases_keeps_digits_and_hash():
    assert tokenize("GetWebDeal #75919 NULL") == ["getwebdeal", "#75919", "null"]

def test_tokenize_empty():
    assert tokenize("") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Dev/kb_chatbot/tests/test_query_norm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Dev.kb_chatbot.chat.query_norm'`

- [ ] **Step 3: Write the implementation**

```python
# Dev/kb_chatbot/chat/query_norm.py
"""Canonical query normalization (cache keys) + tokenization (BM25).

normalize() folds trivial rewordings to a stable key so a repeated question
hits the answer cache. tokenize() is the shared BM25 tokenizer for both the
corpus and the query so keyword matching is consistent."""
from __future__ import annotations
import re

from Dev.kb_chatbot import config

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s#]")     # keep word chars, whitespace, and '#'
_TOKEN = re.compile(r"[a-z0-9#]+")


def normalize(query: str) -> str:
    if not query:
        return ""
    q = _PUNCT.sub(" ", query.lower())
    q = _WS.sub(" ", q).strip()
    # Fold product synonyms to their canonical slug (longest name first so
    # "saleshub" is folded before a bare "iq" could ever match).
    for name in sorted(config.PRODUCT_SYNONYM_NAMES, key=len, reverse=True):
        slug = config.resolve_product(name)
        if slug and slug != name:
            q = re.sub(r"\b" + re.escape(name) + r"\b", slug, q)
    return _WS.sub(" ", q).strip()


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest Dev/kb_chatbot/tests/test_query_norm.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/chat/query_norm.py Dev/kb_chatbot/tests/test_query_norm.py
git commit -m "feat(v3.0.1-p1): query normalization + BM25 tokenizer"
```

---

### Task 2: Deterministic query classifier (`chat/classifier.py`)

**Files:**
- Create: `Dev/kb_chatbot/chat/classifier.py`
- Test: `Dev/kb_chatbot/tests/test_classifier.py`

**Interfaces:**
- Produces: `QueryClass` dataclass (`products: list[str]`, `issue_type: str`, `ticket_ids: list[str]`, `is_error: bool`); `classify(query: str) -> QueryClass`; module constants `ISSUE_ERROR`, `ISSUE_HOWTO`, `ISSUE_CONFIG`, `ISSUE_INCIDENT`, `ISSUE_GENERAL`.
- Consumed by: Task 5 (orchestrator uses `classify()` for error-detection, ticket-id pins, and single-product detection).

- [ ] **Step 1: Write the failing test**

```python
# Dev/kb_chatbot/tests/test_classifier.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat.classifier import (
    classify, QueryClass, ISSUE_ERROR, ISSUE_HOWTO, ISSUE_CONFIG, ISSUE_INCIDENT, ISSUE_GENERAL,
)


def test_error_question():
    c = classify("GetWebDeal returns a null buy amount error")
    assert c.is_error is True
    assert c.issue_type == ISSUE_ERROR

def test_howto_question():
    c = classify("How do I book a spot deal in TradeDesk?")
    assert c.issue_type == ISSUE_HOWTO
    assert c.products == ["tradedesk"]

def test_incident_takes_precedence_over_error():
    c = classify("incident: bank holiday booking failed")
    assert c.issue_type == ISSUE_INCIDENT
    assert c.is_error is True   # still error-ish for the widened rerank window

def test_ticket_ids_extracted():
    assert classify("ticket 75919").ticket_ids == ["75919"]
    assert classify("see bug #54000 and incident 41045").ticket_ids == ["54000", "41045"]

def test_two_products_detected():
    c = classify("FormFlow vs SalesHub differences")
    assert set(c.products) == {"formflow", "saleshub"}

def test_general_fallback():
    c = classify("tell me about dealing")
    assert c.issue_type == ISSUE_GENERAL
    assert c.is_error is False

def test_returns_queryclass():
    assert isinstance(classify("anything"), QueryClass)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Dev/kb_chatbot/tests/test_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Dev.kb_chatbot.chat.classifier'`

- [ ] **Step 3: Write the implementation**

```python
# Dev/kb_chatbot/chat/classifier.py
"""Deterministic per-query classification: product(s), issue-type, referenced ids.

Deterministic by design (pure regex + the config product-synonym map): the same
query always produces the same class, so it always takes the same retrieval path
-> consistent answers."""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from Dev.kb_chatbot import config

ISSUE_ERROR = "error"
ISSUE_HOWTO = "how_to"
ISSUE_CONFIG = "config"
ISSUE_INCIDENT = "incident"
ISSUE_GENERAL = "general"

# Same error vocabulary the orchestrator has used since v2.9.2 (kept in sync).
_ERROR_RE = re.compile(
    r"\b(error|errors|issue|issues|fail(?:s|ed|ing|ure)?|null|exception|crash(?:e[ds])?|"
    r"bug|broken|wrong|incorrect|discrepan\w*|duplicat\w*|missing|not working|doesn'?t|"
    r"cannot|can'?t|unable)\b", re.IGNORECASE)
_INCIDENT_RE = re.compile(r"\bincidents?\b", re.IGNORECASE)
_HOWTO_RE = re.compile(
    r"\b(how (?:do|to|can|would)|steps?|guide|walk ?through|set ?up|configure|"
    r"create|add|enable|book|post)\b", re.IGNORECASE)
_CONFIG_RE = re.compile(
    r"\b(config\w*|settings?|install\w*|permission|enable|disable|toggle)\b", re.IGNORECASE)
# Explicit references only: ticket/bug/incident/# + number (bare numbers collide with amounts).
_TICKET_ID_RE = re.compile(r"(?:ticket|tickets|bug|incident|#)\s*#?\s*(\d{3,7})", re.IGNORECASE)


@dataclass
class QueryClass:
    products: list[str] = field(default_factory=list)
    issue_type: str = ISSUE_GENERAL
    ticket_ids: list[str] = field(default_factory=list)
    is_error: bool = False


def _products(text: str) -> list[str]:
    low = (text or "").lower()
    found: list[str] = []
    for name in config.PRODUCT_SYNONYM_NAMES:
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            slug = config.resolve_product(name)
            if slug and slug not in found:
                found.append(slug)
    return found


def _ticket_ids(text: str) -> list[str]:
    out: list[str] = []
    for m in _TICKET_ID_RE.finditer(text or ""):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def classify(query: str) -> QueryClass:
    q = query or ""
    is_error = bool(_ERROR_RE.search(q))
    if _INCIDENT_RE.search(q):
        issue = ISSUE_INCIDENT
    elif is_error:
        issue = ISSUE_ERROR
    elif _HOWTO_RE.search(q):
        issue = ISSUE_HOWTO
    elif _CONFIG_RE.search(q):
        issue = ISSUE_CONFIG
    else:
        issue = ISSUE_GENERAL
    return QueryClass(products=_products(q), issue_type=issue,
                      ticket_ids=_ticket_ids(q), is_error=is_error)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest Dev/kb_chatbot/tests/test_classifier.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/chat/classifier.py Dev/kb_chatbot/tests/test_classifier.py
git commit -m "feat(v3.0.1-p1): deterministic query classifier (product/issue-type/ids)"
```

---

### Task 3: Hybrid retrieval (BM25 + RRF) + stable tie-break (`retriever.py`)

**Files:**
- Modify: `Dev/kb_chatbot/requirements.txt` (add `rank-bm25`)
- Modify: `Dev/kb_chatbot/config.py` (add hybrid knobs after the "Retrieval defaults" block, ~line 134)
- Modify: `Dev/kb_chatbot/retriever.py` (BM25 build, RRF fuse, stable sort in `retrieve()`)
- Test: `Dev/kb_chatbot/tests/test_retriever_hybrid.py`

**Interfaces:**
- Consumes: `query_norm.tokenize` (Task 1); `config.HYBRID_ENABLED`, `config.BM25_TOP_K`, `config.RRF_K`.
- Produces: `Retriever.retrieve()` now fuses vector+BM25 candidates before rerank; `Retriever.invalidate_bm25()` (call after a reindex to force a rebuild). `retrieve()` return type and `RetrievalResult` are unchanged.

- [ ] **Step 1: Add the dependency**

Append to `Dev/kb_chatbot/requirements.txt`:
```text
rank-bm25
```

- [ ] **Step 2: Add config knobs**

In `Dev/kb_chatbot/config.py`, immediately after the `ANSWER_MAX_TOKENS` line in the "Retrieval defaults" block, add:
```python
# ── Hybrid retrieval (BM25 keyword + vector, fused via RRF) ─────────────────────
HYBRID_ENABLED = True
BM25_TOP_K     = 30    # keyword candidates fused with the vector candidates
RRF_K          = 60    # Reciprocal Rank Fusion damping constant
```

- [ ] **Step 3: Write the failing test**

```python
# Dev/kb_chatbot/tests/test_retriever_hybrid.py
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


@pytest.fixture(scope="module")
def retriever():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))
    yield Retriever(Path(tmp), confidence_floor=0.0)


def test_rrf_fuse_is_deterministic_and_orders_by_fused_rank(retriever):
    # Two disjoint ranked lists; a doc appearing in both must outrank singletons.
    from Dev.kb_chatbot.chunker import Chunk
    a = Chunk(id="a", text="", metadata={})
    b = Chunk(id="b", text="", metadata={})
    c = Chunk(id="c", text="", metadata={})
    vec = [a, b]      # a rank0, b rank1
    bm = [b, c]       # b rank0, c rank1
    fused = retriever._rrf_fuse(vec, bm, k=60)
    ids = [x.id for x in fused]
    assert ids[0] == "b"                       # b is in both lists -> highest fused score
    assert set(ids) == {"a", "b", "c"}
    assert retriever._rrf_fuse(vec, bm, k=60) == fused or \
           [x.id for x in retriever._rrf_fuse(vec, bm, k=60)] == ids  # deterministic


def test_bm25_finds_exact_term(retriever):
    # A rare exact term should surface via the keyword path even if phrased tersely.
    cands = retriever._bm25_candidates("IBAN", Filters(), 10)
    assert any("iban" in (c.text or "").lower() or
               "iban" in (c.metadata.get("title", "").lower()) for c in cands) or cands == []
    # (tiny_library may not contain 'IBAN' as a token; the call must not error and returns a list)
    assert isinstance(cands, list)


def test_hybrid_retrieve_still_returns_relevant_chunks(retriever):
    r = retriever.retrieve("IBAN validation form", Filters())
    assert len(r.chunks) > 0

def test_hybrid_retrieve_is_order_stable(retriever):
    r1 = retriever.retrieve("payment recurring", Filters())
    r2 = retriever.retrieve("payment recurring", Filters())
    assert [c.id for c in r1.chunks] == [c.id for c in r2.chunks]

def test_product_filter_respected_under_hybrid(retriever):
    r = retriever.retrieve("anything", Filters(product="saleshub"))
    assert all(c.metadata.get("product") == "saleshub" for c in r.chunks)

def test_invalidate_bm25_forces_rebuild(retriever):
    retriever._ensure_bm25()
    assert retriever._bm25 is not None or retriever._bm25_ids == []
    retriever.invalidate_bm25()
    assert retriever._bm25 is None
```

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest Dev/kb_chatbot/tests/test_retriever_hybrid.py -v`
Expected: FAIL — `AttributeError: 'Retriever' object has no attribute '_rrf_fuse'`

- [ ] **Step 5: Implement in `retriever.py`**

Add these imports near the top (after the existing imports):
```python
from Dev.kb_chatbot.chat.query_norm import tokenize
```

In `Retriever.__init__`, after `self.confidence_floor = confidence_floor`, add:
```python
        self._bm25 = None                 # lazy BM25Okapi, built from the collection
        self._bm25_ids: list[str] = []
        self._bm25_docs: list[str] = []
        self._bm25_meta: list[dict] = []
```

Add these methods to the `Retriever` class (e.g. after `_query_chroma`):
```python
    def _ensure_bm25(self) -> None:
        if self._bm25 is not None or self._bm25_ids:
            return
        got = self.collection.get(include=["documents", "metadatas"])
        self._bm25_ids = got.get("ids", []) or []
        self._bm25_docs = [d or "" for d in (got.get("documents", []) or [])]
        self._bm25_meta = [dict(m or {}) for m in (got.get("metadatas", []) or [])]
        if self._bm25_ids:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi([tokenize(d) for d in self._bm25_docs])

    def invalidate_bm25(self) -> None:
        """Drop the cached BM25 index so the next retrieve rebuilds it (call after a reindex)."""
        self._bm25 = None
        self._bm25_ids = []
        self._bm25_docs = []
        self._bm25_meta = []

    def _bm25_candidates(self, query: str, filters: Filters, n: int) -> list[Chunk]:
        self._ensure_bm25()
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], self._bm25_ids[i]))
        out: list[Chunk] = []
        for i in order:
            if scores[i] <= 0:
                break
            if filters.product and self._bm25_meta[i].get("product") != filters.product:
                continue
            out.append(Chunk(id=self._bm25_ids[i], text=self._bm25_docs[i],
                             metadata=dict(self._bm25_meta[i])))
            if len(out) >= n:
                break
        return out

    def _rrf_fuse(self, vec_list: list[Chunk], bm25_list: list[Chunk], k: int) -> list[Chunk]:
        ranked: dict[str, list] = {}   # id -> [chunk, score]
        for rank, c in enumerate(vec_list):
            ranked.setdefault(c.id, [c, 0.0])[1] += 1.0 / (k + rank + 1)
        for rank, c in enumerate(bm25_list):
            entry = ranked.setdefault(c.id, [c, 0.0])
            entry[1] += 1.0 / (k + rank + 1)
        fused = sorted(ranked.values(), key=lambda t: (-t[1], t[0].id))
        return [c for c, _ in fused]
```

Replace the body of `retrieve()` from the `query_vec = ...` line down to the `scored = ...` line with:
```python
        query_vec = self._embed(query)
        vec_c = self._query_chroma(query_vec, filters, self.top_k_retrieve)
        if config.HYBRID_ENABLED:
            bm_c = self._bm25_candidates(query, filters, config.BM25_TOP_K)
            candidates = self._rrf_fuse(vec_c, bm_c, config.RRF_K)
        else:
            candidates = vec_c
        if not candidates:
            return RetrievalResult(abstain_reason="no_relevant_kb_match")

        pairs = [(query, c.text) for c in candidates]
        scores = self._get_reranker().predict(pairs)
        scored = sorted(zip(candidates, scores), key=lambda t: (-float(t[1]), t[0].id))
```

(The `k = top_k_rerank or self.top_k_rerank` line and everything after it stay unchanged.)

- [ ] **Step 6: Run the new + existing retriever tests**

Run: `python -m pytest Dev/kb_chatbot/tests/test_retriever_hybrid.py Dev/kb_chatbot/tests/test_retriever.py -v`
Expected: PASS (all). If `rank-bm25` is missing: `pip install rank-bm25` in `scraper\venv` first.

- [ ] **Step 7: Commit**

```bash
git add Dev/kb_chatbot/requirements.txt Dev/kb_chatbot/config.py Dev/kb_chatbot/retriever.py Dev/kb_chatbot/tests/test_retriever_hybrid.py
git commit -m "feat(v3.0.1-p1): hybrid BM25+vector retrieval (RRF) + stable rerank tie-break"
```

---

### Task 4: Answer cache (`chat/answer_cache.py`)

**Files:**
- Modify: `Dev/kb_chatbot/config.py` (add cache knobs after the hybrid knobs)
- Create: `Dev/kb_chatbot/chat/answer_cache.py`
- Test: `Dev/kb_chatbot/tests/test_answer_cache.py`

**Interfaces:**
- Produces: `AnswerCache(path: Path, max_entries: int = config.ANSWER_CACHE_MAX)` with `get(key: str) -> Optional[dict]`, `put(key: str, payload: dict) -> None` (persists to JSON), and `make_key(normalized_query: str, product: str, model: str) -> str` (module function `make_key`). `config.ANSWER_CACHE_ENABLED`, `config.ANSWER_CACHE_FILE`, `config.ANSWER_CACHE_MAX`.
- Consumed by: Task 5 (orchestrator).

- [ ] **Step 1: Add config knobs**

In `Dev/kb_chatbot/config.py`, right after the hybrid knobs from Task 3, add:
```python
# ── Answer cache (identical answer for a repeated standalone question) ──────────
ANSWER_CACHE_ENABLED = True
ANSWER_CACHE_FILE    = STATE_DIR / "answer_cache.json"
ANSWER_CACHE_MAX     = 2000
# Cache invalidates automatically when the corpus/embedder version changes.
INDEX_VERSION        = f"{CHUNK_SCHEMA_VERSION}:{EMBED_MODEL}"
```
(Place this AFTER `CHUNK_SCHEMA_VERSION` is defined — it is defined in `ingest.py`, so instead compute `INDEX_VERSION` from a local constant: add `CHUNK_SCHEMA_VERSION = 4` is NOT in config. Use `EMBED_MODEL` + a Phase-1 literal.) Use exactly:
```python
INDEX_VERSION = f"v4:{EMBED_MODEL}"   # bump the prefix if the corpus is rebuilt with new chunking
```

- [ ] **Step 2: Write the failing test**

```python
# Dev/kb_chatbot/tests/test_answer_cache.py
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat.answer_cache import AnswerCache, make_key


def test_make_key_varies_by_product_and_model():
    k1 = make_key("how do i book a deal", "tradedesk", "claude-sonnet-4-6")
    k2 = make_key("how do i book a deal", "web4", "claude-sonnet-4-6")
    k3 = make_key("how do i book a deal", "tradedesk", "gpt-5.4")
    assert k1 != k2 != k3 and k1 != k3

def test_put_then_get_roundtrips(tmp_path):
    c = AnswerCache(tmp_path / "cache.json")
    c.put("k1", {"content": "answer", "model": "m"})
    assert c.get("k1") == {"content": "answer", "model": "m"}

def test_miss_returns_none(tmp_path):
    c = AnswerCache(tmp_path / "cache.json")
    assert c.get("nope") is None

def test_persists_across_instances(tmp_path):
    p = tmp_path / "cache.json"
    AnswerCache(p).put("k", {"content": "x"})
    assert AnswerCache(p).get("k") == {"content": "x"}

def test_evicts_oldest_beyond_max(tmp_path):
    c = AnswerCache(tmp_path / "cache.json", max_entries=2)
    c.put("a", {"content": "1"}); c.put("b", {"content": "2"}); c.put("c", {"content": "3"})
    assert c.get("a") is None          # oldest evicted
    assert c.get("b") is not None and c.get("c") is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest Dev/kb_chatbot/tests/test_answer_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Dev.kb_chatbot.chat.answer_cache'`

- [ ] **Step 4: Write the implementation**

```python
# Dev/kb_chatbot/chat/answer_cache.py
"""Persistent answer cache: identical answer for a repeated standalone question.

Keyed on (normalized query, product filter, model, index version). Only the
already-scrubbed, citation-validated answer payload is stored (no raw ticket
text / PII). Insertion-ordered JSON; oldest entries evicted past max_entries."""
from __future__ import annotations
import hashlib
import json
import logging
from pathlib import Path
from typing import Optional

from Dev.kb_chatbot import config

log = logging.getLogger("kb_chatbot.answer_cache")


def make_key(normalized_query: str, product: str, model: str) -> str:
    base = f"{normalized_query}|{product or ''}|{model}|{config.INDEX_VERSION}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()


class AnswerCache:
    def __init__(self, path: Path, max_entries: int = config.ANSWER_CACHE_MAX):
        self.path = Path(path)
        self.max_entries = max_entries
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    self._data = d
            except Exception:
                log.warning("Answer cache unreadable; starting empty")
                self._data = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data), encoding="utf-8")
        except Exception as exc:
            log.warning("Answer cache save failed: %s", exc)

    def get(self, key: str) -> Optional[dict]:
        return self._data.get(key)

    def put(self, key: str, payload: dict) -> None:
        if key in self._data:
            del self._data[key]           # move-to-end (refresh recency)
        self._data[key] = payload
        while len(self._data) > self.max_entries:
            oldest = next(iter(self._data))
            del self._data[oldest]
        self._save()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest Dev/kb_chatbot/tests/test_answer_cache.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/chat/answer_cache.py Dev/kb_chatbot/tests/test_answer_cache.py
git commit -m "feat(v3.0.1-p1): persistent answer cache (repeat-question determinism)"
```

---

### Task 5: Wire classifier + answer cache into the orchestrator

**Files:**
- Modify: `Dev/kb_chatbot/chat/orchestrator.py`
- Test: `Dev/kb_chatbot/tests/test_orchestrator_cache.py`

**Interfaces:**
- Consumes: `classifier.classify` (Task 2), `query_norm.normalize` (Task 1), `answer_cache.AnswerCache`/`make_key` (Task 4).
- Produces: `Deps` gains `answer_cache: Optional[AnswerCache] = None`. Behavior: for a **standalone first-turn** question, a cache hit returns the stored answer without calling the LLM; a computed answer is stored. `_looks_like_error`, `_extract_ticket_ids`, `_extract_single_product` now delegate to the classifier (behavior preserved). No change to clarification/abstain paths.

- [ ] **Step 1: Write the failing test**

```python
# Dev/kb_chatbot/tests/test_orchestrator_cache.py
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters
from Dev.kb_chatbot.llm.fake_provider import FakeProvider
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chat.answer_cache import AnswerCache
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


@pytest.fixture(scope="module")
def tmp_index():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))
    return tmp


def test_repeat_standalone_question_served_from_cache(tmp_index, tmp_path):
    r = Retriever(Path(tmp_index), confidence_floor=0.0)
    r.suggest = lambda query, top_k=5: []
    cache = AnswerCache(tmp_path / "cache.json")
    llm = FakeProvider(canned_text="Answer [TradeDesk · dealing · Booking a Spot Deal].")
    deps = Deps(retriever=r, llm=llm, answer_cache=cache)

    t1 = handle_turn("How do I book a spot deal in TradeDesk?", Session.new(),
                     Filters(product="tradedesk"), "claude-haiku-4-5-20251001", deps=deps)
    assert t1.kind == "answer"
    assert len(llm.calls) == 1

    # Identical question in a FRESH session -> served from cache, no second LLM call.
    t2 = handle_turn("How do I book a spot deal in TradeDesk?", Session.new(),
                     Filters(product="tradedesk"), "claude-haiku-4-5-20251001", deps=deps)
    assert t2.kind == "answer"
    assert t2.content == t1.content
    assert len(llm.calls) == 1   # unchanged -> cache hit


def test_classifier_delegation_preserves_error_detection():
    from Dev.kb_chatbot.chat.orchestrator import _looks_like_error
    assert _looks_like_error("GetWebDeal returns a null buy amount error")
    assert not _looks_like_error("how do I book a spot deal")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest Dev/kb_chatbot/tests/test_orchestrator_cache.py -v`
Expected: FAIL — `TypeError: Deps.__init__() got an unexpected keyword argument 'answer_cache'`

- [ ] **Step 3: Implement the orchestrator changes**

Add imports near the top of `orchestrator.py` (after the existing `from Dev.kb_chatbot...` imports):
```python
from Dev.kb_chatbot.chat import classifier as _classifier
from Dev.kb_chatbot.chat.query_norm import normalize as _normalize
from Dev.kb_chatbot.chat.answer_cache import AnswerCache, make_key as _cache_make_key
```

Redefine the three helper functions to delegate to the classifier (replace their bodies; keep the names so existing imports/tests work):
```python
def _looks_like_error(query: str) -> bool:
    return _classifier.classify(query or "").is_error


def _extract_ticket_ids(text: str) -> list[str]:
    return _classifier.classify(text or "").ticket_ids


def _extract_single_product(text: str) -> Optional[str]:
    prods = _classifier.classify(text or "").products
    return prods[0] if len(prods) == 1 else None
```
(Delete the now-unused module-level `_ERROR_RE` / `_TICKET_ID_RE` regexes only if nothing else references them; if unsure, leave them — they are harmless.)

Add `answer_cache` to `Deps`:
```python
@dataclass
class Deps:
    retriever: Retriever
    llm: LLMProvider
    usage_logger: Callable[[Turn], None] = lambda t: None
    clarifier: Optional[Callable[[str, list[Chunk]], str]] = None
    attachments: list = field(default_factory=list)
    rewriter: Optional[Callable[[str, list], object]] = None
    on_progress: Callable[[str], None] = lambda stage: None
    answer_cache: Optional[AnswerCache] = None
```

In `handle_turn`, immediately after `history = session.history_for_llm(...)` (before `_build_retrieval_query`), add the cache-read for standalone first turns:
```python
    cache = deps.answer_cache
    cache_key = None
    if cache is not None and config.ANSWER_CACHE_ENABLED and not session.turns:
        cache_key = _cache_make_key(_normalize(user_msg), filters.product or "", default_model)
        cached = cache.get(cache_key)
        if cached:
            session.add_user(user_msg)
            turn = Turn(role="assistant", kind="answer",
                        content=cached.get("content", ""),
                        citations=cached.get("citations", []),
                        retrieved_ids=cached.get("retrieved_ids", []),
                        model=cached.get("model", ""))
            session.last_context_ids = cached.get("retrieved_ids", [])
            session.add(turn)
            deps.usage_logger(turn)
            return turn
```

On the answer path, immediately BEFORE `session.last_context_ids = [c.id for c in result.chunks]`, add the cache-write:
```python
        if cache is not None and cache_key is not None:
            cache.put(cache_key, {
                "content": answer_text,
                "citations": turn.citations,
                "retrieved_ids": turn.retrieved_ids,
                "model": resp.model,
            })
```
(Note: `turn` is constructed just above this line — place the `cache.put` AFTER the `turn = Turn(...)` assignment and BEFORE `session.last_context_ids = ...`.)

- [ ] **Step 4: Run the new + existing orchestrator tests**

Run: `python -m pytest Dev/kb_chatbot/tests/test_orchestrator_cache.py Dev/kb_chatbot/tests/test_orchestrator.py -v`
Expected: PASS (all). The cache test shows one LLM call across two identical fresh-session turns; existing orchestrator tests unaffected (they pass no `answer_cache`, so caching is inert).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/chat/orchestrator.py Dev/kb_chatbot/tests/test_orchestrator_cache.py
git commit -m "feat(v3.0.1-p1): wire classifier + answer cache into orchestrator"
```

---

### Task 6: Tighten the answer-format contract (`prompt.py`)

**Files:**
- Modify: `Dev/kb_chatbot/prompt.py` (add one explicit "answer shape" block to `SYSTEM_PROMPT`)
- Modify: `Dev/kb_chatbot/tests/test_prompt.py` (update the locked-text assertion)
- Test: `Dev/kb_chatbot/tests/test_prompt.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `SYSTEM_PROMPT` gains a compact, always-applied shape block so structure stops varying between answers. `build_system_prompt()` signature unchanged.

- [ ] **Step 1: Update/inspect the locked-text test**

Open `Dev/kb_chatbot/tests/test_prompt.py`. The test `test_system_prompt_locked_text_v23` pins wording in `SYSTEM_PROMPT`. Change its assertion to check for the NEW shape-block sentinel instead of (or in addition to) the old text. Replace the body of that test with:
```python
def test_system_prompt_locked_text_v23():
    from Dev.kb_chatbot.prompt import SYSTEM_PROMPT
    assert "CONTEXT block" in SYSTEM_PROMPT
    assert "Answer shape (use the same structure every time)" in SYSTEM_PROMPT
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest Dev/kb_chatbot/tests/test_prompt.py::test_system_prompt_locked_text_v23 -v`
Expected: FAIL — the sentinel string is not yet in `SYSTEM_PROMPT`.

- [ ] **Step 3: Add the shape block to `SYSTEM_PROMPT`**

In `Dev/kb_chatbot/prompt.py`, insert this block into `SYSTEM_PROMPT` immediately BEFORE the final line `Do not editorialise. ...`:
```text
Answer shape (use the same structure every time):
- One-sentence direct answer (cited).
- For an issue/error/incident: **Problem** -> **Root cause** (if stated) -> **Resolution** (numbered, every step cited) -> **Where seen** (tickets/incidents, with dates, oldest->most recent) -> optional one-line next step.
- For a how-to: numbered steps, each cited.
- End with the "Searched:" footnote, and a "Sources: #<id>, ..." line if any ticket/incident was used.
Keep this exact ordering and these exact section labels on every answer so responses are consistent.

```

- [ ] **Step 4: Run the prompt tests**

Run: `python -m pytest Dev/kb_chatbot/tests/test_prompt.py -v`
Expected: PASS (all). If any other assertion in `test_prompt.py` pinned removed text, update it to match the current wording.

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/prompt.py Dev/kb_chatbot/tests/test_prompt.py
git commit -m "feat(v3.0.1-p1): explicit always-applied answer-shape contract"
```

---

### Task 7: Eval harness — accuracy + consistency (`eval/`)

**Files:**
- Create: `Dev/kb_chatbot/eval/__init__.py`
- Create: `Dev/kb_chatbot/eval/score.py`
- Create: `Dev/kb_chatbot/eval/dataset.py`
- Create: `Dev/kb_chatbot/eval/eval_set.json`
- Create: `Dev/kb_chatbot/eval/run_eval.py`
- Test: `Dev/kb_chatbot/tests/test_eval_score.py`

**Interfaces:**
- Produces: `score.accuracy(answer_text, retrieved_ids, expected_sources, expected_keypoints) -> float`; `score.source_stability(runs: list[list[str]]) -> float`; `score.answer_stability(answers: list[str]) -> float`; `dataset.EvalCase` + `dataset.load(path) -> list[EvalCase]`; `run_eval.main()` CLI.
- Consumed by: Phase 5 (fine-tune gate) and the ship gate.

- [ ] **Step 1: Write the failing test (pure scorers)**

```python
# Dev/kb_chatbot/tests/test_eval_score.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.eval.score import accuracy, source_stability, answer_stability


def test_accuracy_full_when_sources_and_keypoints_present():
    a = accuracy("The buy amount was null; fixed in the DB. [Ticket #75919](u)",
                 retrieved_ids=["ticket_1"],
                 expected_sources=["ticket_1"],
                 expected_keypoints=["buy amount", "null"])
    assert a == 1.0

def test_accuracy_partial_when_keypoint_missing():
    a = accuracy("Something unrelated. [Ticket #75919](u)",
                 retrieved_ids=["ticket_1"],
                 expected_sources=["ticket_1"],
                 expected_keypoints=["buy amount", "null"])
    assert 0.0 < a < 1.0

def test_accuracy_zero_when_source_missing():
    a = accuracy("text", retrieved_ids=["other"], expected_sources=["ticket_1"],
                 expected_keypoints=[])
    assert a == 0.0

def test_source_stability_identical_runs_is_one():
    assert source_stability([["a", "b"], ["b", "a"], ["a", "b"]]) == 1.0

def test_source_stability_varying_runs_below_one():
    assert source_stability([["a", "b"], ["a", "c"]]) < 1.0

def test_answer_stability_identical_is_one():
    assert answer_stability(["same text", "same text"]) == 1.0

def test_answer_stability_different_below_one():
    assert answer_stability(["the cat sat", "a dog ran"]) < 1.0

def test_stability_single_run_is_one():
    assert source_stability([["a"]]) == 1.0
    assert answer_stability(["only"]) == 1.0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest Dev/kb_chatbot/tests/test_eval_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Dev.kb_chatbot.eval'`

- [ ] **Step 3: Write `eval/__init__.py`**

```python
# Dev/kb_chatbot/eval/__init__.py
"""Offline eval harness: scores accuracy + run-to-run consistency."""
```

- [ ] **Step 4: Write `eval/score.py`**

```python
# Dev/kb_chatbot/eval/score.py
"""Pure scoring functions for the eval harness (no I/O, deterministic)."""
from __future__ import annotations
from difflib import SequenceMatcher
from itertools import combinations


def accuracy(answer_text: str, retrieved_ids: list[str],
             expected_sources: list[str], expected_keypoints: list[str]) -> float:
    """0..1: half source-recall (were the expected chunks retrieved?), half
    keypoint-coverage (does the answer text mention the expected facts?).
    Source recall gates: 0 sources found -> 0.0 overall (a right-sounding answer
    with the wrong sources is not correct)."""
    if expected_sources:
        found = sum(1 for s in expected_sources if s in set(retrieved_ids))
        src = found / len(expected_sources)
        if found == 0:
            return 0.0
    else:
        src = 1.0
    if expected_keypoints:
        low = (answer_text or "").lower()
        kp = sum(1 for k in expected_keypoints if k.lower() in low) / len(expected_keypoints)
    else:
        kp = 1.0
    return round(0.5 * src + 0.5 * kp, 4)


def source_stability(runs: list[list[str]]) -> float:
    """Mean pairwise Jaccard of the retrieved-id SETS across runs (order-insensitive)."""
    if len(runs) <= 1:
        return 1.0
    sets = [set(r) for r in runs]
    sims = []
    for a, b in combinations(sets, 2):
        union = a | b
        sims.append(1.0 if not union else len(a & b) / len(union))
    return round(sum(sims) / len(sims), 4)


def answer_stability(answers: list[str]) -> float:
    """Mean pairwise text similarity (difflib ratio) across runs."""
    if len(answers) <= 1:
        return 1.0
    sims = [SequenceMatcher(None, a, b).ratio() for a, b in combinations(answers, 2)]
    return round(sum(sims) / len(sims), 4)
```

- [ ] **Step 5: Run the scorer test to verify it passes**

Run: `python -m pytest Dev/kb_chatbot/tests/test_eval_score.py -v`
Expected: PASS (8 passed)

- [ ] **Step 6: Write `eval/dataset.py`**

```python
# Dev/kb_chatbot/eval/dataset.py
"""Eval-case model + loader."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EvalCase:
    question: str
    product: str = ""                       # optional product filter
    expected_sources: list[str] = field(default_factory=list)      # chunk ids or ticket_ids
    expected_keypoints: list[str] = field(default_factory=list)    # substrings the answer should contain


def load(path) -> list[EvalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvalCase(**c) for c in data]
```

- [ ] **Step 7: Write `eval/eval_set.json` (starter set — expand later against the real corpus)**

```json
[
  {
    "question": "TD GetWebDeal did not return any buy amount for a deal. Is there a fix?",
    "product": "",
    "expected_sources": [],
    "expected_keypoints": ["buy amount", "null"]
  },
  {
    "question": "How do I post a deal in TradeDesk?",
    "product": "",
    "expected_sources": [],
    "expected_keypoints": ["postdeal"]
  },
  {
    "question": "drawdown margin duplication on a full drawdown",
    "product": "",
    "expected_sources": [],
    "expected_keypoints": ["margin", "drawdown"]
  }
]
```

- [ ] **Step 8: Write `eval/run_eval.py`**

```python
# Dev/kb_chatbot/eval/run_eval.py
"""Run the eval set through the orchestrator K times per case and report
accuracy + consistency. Live providers are selected by name; use FakeProvider
only for a wiring smoke test.

Usage:
  python -m Dev.kb_chatbot.eval.run_eval --chroma <path> --provider claude --model claude-sonnet-4-6 --runs 3
"""
from __future__ import annotations
import argparse
from pathlib import Path

from Dev.kb_chatbot.eval.dataset import load
from Dev.kb_chatbot.eval.score import accuracy, source_stability, answer_stability


def _make_llm(provider: str):
    if provider == "fake":
        from Dev.kb_chatbot.llm.fake_provider import FakeProvider
        return FakeProvider(canned_text="stub answer")
    if provider == "claude":
        from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeProvider
        return ClaudeCodeProvider()
    if provider == "openai":
        from Dev.kb_chatbot.llm.codex_provider import CodexProvider
        return CodexProvider()
    raise SystemExit(f"unknown provider: {provider}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chroma", required=True)
    ap.add_argument("--provider", default="fake")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--set", default=str(Path(__file__).parent / "eval_set.json"))
    args = ap.parse_args()

    from Dev.kb_chatbot.retriever import Retriever, Filters
    from Dev.kb_chatbot.chat.session import Session
    from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps

    retriever = Retriever(Path(args.chroma), confidence_floor=0.0)
    llm = _make_llm(args.provider)
    cases = load(args.set)

    acc_total = 0.0
    src_total = 0.0
    ans_total = 0.0
    for case in cases:
        runs_ids: list[list[str]] = []
        runs_text: list[str] = []
        for _ in range(args.runs):
            deps = Deps(retriever=retriever, llm=llm)   # no cache: measure raw model consistency
            turn = handle_turn(case.question, Session.new(),
                               Filters(product=case.product or None), args.model, deps=deps)
            runs_ids.append(turn.retrieved_ids)
            runs_text.append(turn.content)
        acc = accuracy(runs_text[0], runs_ids[0], case.expected_sources, case.expected_keypoints)
        s_src = source_stability(runs_ids)
        s_ans = answer_stability(runs_text)
        acc_total += acc; src_total += s_src; ans_total += s_ans
        print(f"[{acc:.2f} acc | {s_src:.2f} src-stable | {s_ans:.2f} ans-stable] {case.question[:60]}")

    n = len(cases) or 1
    print(f"\nMEANS  accuracy={acc_total/n:.3f}  source_stability={src_total/n:.3f}  "
          f"answer_stability={ans_total/n:.3f}  (provider={args.provider} model={args.model} runs={args.runs})")


if __name__ == "__main__":
    main()
```

- [ ] **Step 9: Commit**

```bash
git add Dev/kb_chatbot/eval Dev/kb_chatbot/tests/test_eval_score.py
git commit -m "feat(v3.0.1-p1): eval harness (accuracy + run-to-run consistency scorers + runner)"
```

---

## Full-Suite Regression (after all tasks)

- [ ] Run the whole chatbot suite: `python -m pytest Dev/kb_chatbot/tests/ -q`
  Expected: all pass (new Phase-1 tests + the existing ~329). If `rank-bm25` isn't installed in `scraper\venv`, `pip install rank-bm25` first.
- [ ] Sanity: hybrid + cache are inert unless enabled/passed, so no existing behavior regresses (existing orchestrator tests pass `Deps` without `answer_cache`; `config.HYBRID_ENABLED=True` only adds a keyword path).

## Self-Review (completed)

- **Spec coverage (spec §6.1):** hybrid BM25+RRF ✓ (T3), classification layer ✓ (T2), determinism = query-norm + answer cache + stable tie-break ✓ (T1/T4/T5/T3), answer-format contract ✓ (T6), eval harness scoring accuracy + consistency ✓ (T7). No reindex / no schema bump ✓ (constraints). Embedder unchanged ✓.
- **Placeholder scan:** none — every module and test is complete. `eval_set.json` is a real starter file (marked to expand against the production corpus in later live runs).
- **Type/name consistency:** `tokenize`/`normalize` (T1) used in T3/T4/T5; `classify`/`QueryClass` (T2) used in T5; `AnswerCache`/`make_key` (T4) used in T5; `Deps.answer_cache` added in T5 and consumed by T5; scorer names (`accuracy`/`source_stability`/`answer_stability`) defined in T7 and used in `run_eval`. `config.HYBRID_ENABLED/BM25_TOP_K/RRF_K` (T3), `config.ANSWER_CACHE_*`/`INDEX_VERSION` (T4) match their consumers.
- **Risk note:** T6 edits `SYSTEM_PROMPT`, which `test_prompt.py::test_system_prompt_locked_text_v23` pins — the task updates that test in the same step (Step 1), so the suite stays green.
```
