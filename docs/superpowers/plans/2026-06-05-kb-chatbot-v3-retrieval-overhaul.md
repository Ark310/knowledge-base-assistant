# KB Chatbot v3 Retrieval Overhaul (Approach C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hybrid BM25+vector retrieval with RRF fusion, domain query expansion, an upgraded reranker, and a golden eval harness — shipped as `dist\ContosoKBChatbot-BETA.exe` with isolated `chatbot_state_beta\`, never touching the stable exe.

**Architecture:** Layered retrieval pipeline. New pure modules (`fusion.py`, `lexical.py`, `expansion.py`) feed an orchestrating `Retriever.retrieve()`; fusion happens *before* the rerank + confidence gate so the citation/abstention contract is unchanged. BM25 is a pickled sidecar rebuilt from chroma on staleness — it can never drift from the vector index. Every accuracy claim is gated by `eval/run_eval.py` against `eval/golden.jsonl`.

**Tech Stack:** Python 3.x in `scraper\venv`, ChromaDB, sentence-transformers (CrossEncoder), rank-bm25, PyYAML, PySide6, PyInstaller (onefile).

**Spec:** `docs/superpowers/specs/2026-06-05-kb-chatbot-v3-retrieval-overhaul-design.md`

---

## Execution context (read first)

- **Workspace:** git worktree `C:\Users\AbdulRaqeebKhatri\OneDrive\Documents\Knowledge Base\.claude\worktrees\kb-chatbot-v3`, branch `dev/kb-chatbot-v3-retrieval-overhaul`. All commands below run from the worktree root.
- **Python:** `..\..\..\scraper\venv\Scripts\python.exe` (shared venv in the main checkout). Referred to below as `$PY`. In PowerShell: `$PY = "..\..\..\scraper\venv\Scripts\python.exe"`.
- **Baseline (verified 2026-06-05):** `$PY -m pytest tests Dev/kb_chatbot/tests -q` → 144 passed (37 scraper + 107 chatbot, ~2 min).
- **KB library for eval ingest:** `..\..\..\library\kb` (1475 article JSONs, verified).
- **Real chat logs for golden-set seeds:** `..\..\..\dist\chatbot_state\chats\*.json` (query text lives here; `usage.jsonl` has **no** query field — spec's seeding source is corrected by Task 8).
- **Never modify anything under `..\..\..\dist\` except adding `ContosoKBChatbot-BETA.exe` via the Task 13 build.**

---

### Task 1: Add rank-bm25 dependency

**Files:**
- Create: `Dev/kb_chatbot/requirements-v3.txt`

- [ ] **Step 1: Install rank-bm25 into the shared venv**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pip install rank-bm25==0.2.2`
Expected: `Successfully installed rank-bm25-0.2.2` (numpy already present).

- [ ] **Step 2: Verify import**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -c "from rank_bm25 import BM25Okapi; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Record the new dependency**

Create `Dev/kb_chatbot/requirements-v3.txt`:

```
# New dependencies introduced by the v3 retrieval overhaul.
# Install into scraper\venv: python -m pip install -r Dev/kb_chatbot/requirements-v3.txt
rank-bm25==0.2.2
```

- [ ] **Step 4: Commit**

```powershell
git add Dev/kb_chatbot/requirements-v3.txt
git commit -m "chore(v3): add rank-bm25 dependency"
```

---

### Task 2: `fusion.py` — Reciprocal Rank Fusion

**Files:**
- Create: `Dev/kb_chatbot/fusion.py`
- Test: `Dev/kb_chatbot/tests/test_fusion.py`

- [ ] **Step 1: Write the failing tests**

Create `Dev/kb_chatbot/tests/test_fusion.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.fusion import rrf_fuse


def test_item_in_both_rankings_beats_item_in_one():
    fused = rrf_fuse([["a", "b", "c"], ["b", "d"]])
    assert fused[0] == "b"          # appears in both lists
    assert set(fused) == {"a", "b", "c", "d"}


def test_preserves_order_within_single_ranking():
    assert rrf_fuse([["x", "y", "z"]]) == ["x", "y", "z"]


def test_empty_rankings_return_empty():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


def test_deterministic_tie_break_by_id():
    # 'a' and 'b' get identical scores (same rank, disjoint lists) → sorted by id
    assert rrf_fuse([["b"], ["a"]]) == ["a", "b"]


def test_k_parameter_dampens_rank_differences():
    # With huge k, rank position barely matters; doc in two lists still wins
    fused = rrf_fuse([["a", "b"], ["c", "b"]], k=10_000)
    assert fused[0] == "b"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_fusion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Dev.kb_chatbot.fusion'`

- [ ] **Step 3: Write the implementation**

Create `Dev/kb_chatbot/fusion.py`:

```python
"""Reciprocal Rank Fusion of multiple ranked id lists. Pure function, no I/O."""
from __future__ import annotations


def rrf_fuse(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Fuse ranked lists of ids via RRF: score(id) = Σ 1/(k + rank + 1).

    Higher fused score ranks first; ties break alphabetically by id so
    results are deterministic across runs."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return [cid for cid, _ in sorted(scores.items(), key=lambda t: (-t[1], t[0]))]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_fusion.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```powershell
git add Dev/kb_chatbot/fusion.py Dev/kb_chatbot/tests/test_fusion.py
git commit -m "feat(v3): RRF fusion of ranked id lists"
```

---

### Task 3: `lexical.py` — BM25 sidecar index

**Files:**
- Create: `Dev/kb_chatbot/lexical.py`
- Test: `Dev/kb_chatbot/tests/test_lexical.py`

- [ ] **Step 1: Write the failing tests**

Create `Dev/kb_chatbot/tests/test_lexical.py`:

```python
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.lexical import LexicalIndex, tokenize, corpus_hash

ITEMS = [
    ("id1", "Booking a spot deal in the dealing tab"),
    ("id2", "Recurring payment sweep failed with ERR-7741"),
    ("id3", "How to build a form in SalesHub form management"),
]


def test_tokenize_lowercases_and_splits_alphanumerics():
    assert tokenize("Sweep failed: ERR-7741!") == ["sweep", "failed", "err", "7741"]


def test_exact_keyword_match_ranks_first():
    idx = LexicalIndex.build(ITEMS)
    assert idx.query("ERR-7741 sweep", top_n=3)[0] == "id2"


def test_query_with_no_overlap_returns_empty():
    idx = LexicalIndex.build(ITEMS)
    assert idx.query("zzz qqq xxx", top_n=3) == []


def test_save_load_roundtrip(tmp_path):
    idx = LexicalIndex.build(ITEMS)
    p = tmp_path / "bm25.pkl"
    idx.save(p)
    loaded = LexicalIndex.load(p)
    assert loaded.ids == idx.ids
    assert loaded.hash == idx.hash
    assert loaded.query("spot deal", top_n=1) == ["id1"]


def test_corpus_hash_is_order_independent_and_content_sensitive():
    assert corpus_hash(["a", "b"]) == corpus_hash(["b", "a"])
    assert corpus_hash(["a", "b"]) != corpus_hash(["a", "c"])


def test_build_empty_corpus_is_safe():
    idx = LexicalIndex.build([])
    assert idx.query("anything", top_n=5) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_lexical.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Dev.kb_chatbot.lexical'`

- [ ] **Step 3: Write the implementation**

Create `Dev/kb_chatbot/lexical.py`:

```python
"""BM25 lexical index sidecar. Built at ingest, pickled next to chroma,
rebuilt from chroma documents whenever the corpus hash no longer matches."""
from __future__ import annotations
import hashlib
import logging
import pickle
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

log = logging.getLogger("kb_chatbot.lexical")

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def corpus_hash(ids: list[str]) -> str:
    h = hashlib.sha1()
    for cid in sorted(ids):
        h.update(cid.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class LexicalIndex:
    def __init__(self, ids: list[str], tokenized: list[list[str]]):
        self.ids = ids
        self._bm25 = BM25Okapi(tokenized) if tokenized else None
        self.hash = corpus_hash(ids)

    @classmethod
    def build(cls, items: list[tuple[str, str]]) -> "LexicalIndex":
        ids = [cid for cid, _ in items]
        return cls(ids, [tokenize(text) for _, text in items])

    def query(self, text: str, top_n: int) -> list[str]:
        """Ranked ids for the query; zero-score matches are dropped."""
        if self._bm25 is None:
            return []
        tokens = tokenize(text)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(zip(self.ids, scores), key=lambda t: t[1], reverse=True)
        return [cid for cid, score in ranked[:top_n] if score > 0.0]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"ids": self.ids, "bm25": self._bm25, "hash": self.hash}, f)

    @classmethod
    def load(cls, path: Path) -> "LexicalIndex":
        with open(path, "rb") as f:
            data = pickle.load(f)
        idx = cls.__new__(cls)
        idx.ids = data["ids"]
        idx._bm25 = data["bm25"]
        idx.hash = data["hash"]
        return idx
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_lexical.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```powershell
git add Dev/kb_chatbot/lexical.py Dev/kb_chatbot/tests/test_lexical.py
git commit -m "feat(v3): BM25 lexical index with pickle persistence and corpus hash"
```

---

### Task 4: `expansion.py` + `data/synonyms.yaml`

**Files:**
- Create: `Dev/kb_chatbot/expansion.py`
- Create: `Dev/kb_chatbot/data/synonyms.yaml`
- Modify: `Dev/kb_chatbot/config.py` (add DATA_DIR / SYNONYMS_FILE; see step 3)
- Test: `Dev/kb_chatbot/tests/test_expansion.py`

- [ ] **Step 1: Write the failing tests**

Create `Dev/kb_chatbot/tests/test_expansion.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.expansion import load_synonyms, expand_query

GROUPS = [["deal", "trade"], ["post", "book"], ["fx rate", "exchange rate"]]


def test_expand_appends_synonyms_of_matched_terms():
    out = expand_query("how do I post a deal", GROUPS)
    assert "book" in out and "trade" in out
    assert out.startswith("how do I post a deal")


def test_expand_matches_whole_words_only():
    # 'posting' must not match the term 'post'... but 'deal' matches exactly
    out = expand_query("dealing with postage", GROUPS)
    assert out == "dealing with postage"


def test_expand_handles_multiword_terms():
    out = expand_query("what is the fx rate today", GROUPS)
    assert "exchange rate" in out


def test_expand_no_duplicates_when_synonym_already_present():
    out = expand_query("post or book a deal", GROUPS)
    assert out.split().count("book") == 1


def test_load_synonyms_reads_groups(tmp_path):
    f = tmp_path / "syn.yaml"
    f.write_text("groups:\n  - [deal, trade]\n  - [post, book]\n", encoding="utf-8")
    assert load_synonyms(f) == [["deal", "trade"], ["post", "book"]]


def test_load_synonyms_malformed_returns_empty(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("groups: {not: [a, list\n", encoding="utf-8")
    assert load_synonyms(f) == []


def test_load_synonyms_missing_file_returns_empty(tmp_path):
    assert load_synonyms(tmp_path / "absent.yaml") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_expansion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Dev.kb_chatbot.expansion'`

- [ ] **Step 3: Write the implementation**

Create `Dev/kb_chatbot/expansion.py`:

```python
"""Domain synonym expansion for the BM25 query side only.
The vector query stays raw — embeddings already handle soft synonymy."""
from __future__ import annotations
import logging
import re
from pathlib import Path

import yaml

log = logging.getLogger("kb_chatbot.expansion")


def load_synonyms(path: Path) -> list[list[str]]:
    """Load synonym groups from YAML ({groups: [[a, b], ...]}).
    Malformed or missing files return [] with a warning — never raise."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("Synonyms file not found: %s — expansion disabled", path)
        return []
    except Exception as exc:
        log.warning("Failed to parse %s: %s — expansion disabled", path, exc)
        return []
    groups = (data or {}).get("groups")
    if not isinstance(groups, list):
        log.warning("Synonyms file %s has no 'groups' list — expansion disabled", path)
        return []
    out: list[list[str]] = []
    for g in groups:
        if isinstance(g, list) and len(g) >= 2 and all(isinstance(t, str) for t in g):
            out.append([t.strip().lower() for t in g])
        else:
            log.warning("Skipping malformed synonym group: %r", g)
    return out


def expand_query(query: str, groups: list[list[str]]) -> str:
    """Append synonyms of any group term found (whole-word) in the query.
    Returns the original query followed by the unique additions."""
    lowered = query.lower()
    additions: list[str] = []
    for group in groups:
        matched = any(
            re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered)
            for term in group
        )
        if not matched:
            continue
        for term in group:
            present = re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered)
            if not present and term not in additions:
                additions.append(term)
    return query if not additions else f"{query} {' '.join(additions)}"
```

Create `Dev/kb_chatbot/data/synonyms.yaml` (starter set — grows with SME feedback):

```yaml
# Contoso domain synonym groups. Each group is a list of equivalent terms;
# matching any term in a query appends the others to the BM25 search only.
groups:
  - [deal, trade]
  - [post, book]
  - [beneficiary, payee]
  - [counterparty, counter-party]
  - [fx, foreign exchange]
  - [rate, exchange rate, fx rate]
  - [wire, wire transfer, payment]
  - [settle, settlement]
  - [drawdown, draw down]
  - [forward, forward contract]
  - [spot, spot deal]
  - [saleshub, saleshub]
  - [tradedesk, tradedesk]
```

Add to `Dev/kb_chatbot/config.py` after the `SETTINGS_FILE` line (line 19):

```python
# ── Bundled data (synonyms etc.) ──────────────────────────────────────────────
if getattr(sys, "frozen", False):
    DATA_DIR = Path(getattr(sys, "_MEIPASS", ".")) / "kb_chatbot_data"
else:
    DATA_DIR = Path(__file__).parent / "data"
SYNONYMS_FILE = DATA_DIR / "synonyms.yaml"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_expansion.py -v`
Expected: 7 passed

- [ ] **Step 5: Run the full chatbot suite (config change touches everything)**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests -q`
Expected: 120 passed (107 baseline + 13 new from Tasks 2–4)

- [ ] **Step 6: Commit**

```powershell
git add Dev/kb_chatbot/expansion.py Dev/kb_chatbot/data/synonyms.yaml Dev/kb_chatbot/config.py Dev/kb_chatbot/tests/test_expansion.py
git commit -m "feat(v3): domain synonym expansion with YAML map (BM25 side only)"
```

---

### Task 5: Ingest builds the BM25 index

**Files:**
- Modify: `Dev/kb_chatbot/ingest.py` (after the upsert loop, ~line 93)
- Modify: `Dev/kb_chatbot/config.py` (add `BM25_FILE`)
- Test: `Dev/kb_chatbot/tests/test_ingest_bm25.py`

- [ ] **Step 1: Write the failing test**

Create `Dev/kb_chatbot/tests/test_ingest_bm25.py`:

```python
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config
from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.lexical import LexicalIndex

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


def test_ingest_writes_loadable_bm25_index():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        pkl = Path(tmp) / config.BM25_FILE
        assert pkl.exists()
        idx = LexicalIndex.load(pkl)
        assert len(idx.ids) == report.chunks_created
        # an exact keyword present in the fixture corpus is findable
        assert idx.query("spot deal booking", top_n=5)


def test_reingest_keeps_index_consistent_with_collection():
    import chromadb
    from Dev.kb_chatbot.ingest import COLLECTION_NAME
    from Dev.kb_chatbot.lexical import corpus_hash
    with tempfile.TemporaryDirectory() as tmp:
        ingest(FIX, Path(tmp))
        ingest(FIX, Path(tmp))  # upsert same content again
        client = chromadb.PersistentClient(path=tmp)
        ids = client.get_collection(COLLECTION_NAME).get(include=[])["ids"]
        client.close()
        idx = LexicalIndex.load(Path(tmp) / config.BM25_FILE)
        assert idx.hash == corpus_hash(ids)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_ingest_bm25.py -v`
Expected: FAIL — `AttributeError: module 'Dev.kb_chatbot.config' has no attribute 'BM25_FILE'`

- [ ] **Step 3: Implement**

Add to `Dev/kb_chatbot/config.py` in the "Retrieval defaults" block (after `CHUNK_TARGET_WORDS`, line 44):

```python
BM25_FILE           = "bm25.pkl"     # lives inside the chroma dir
```

In `Dev/kb_chatbot/ingest.py`, add the import at the top with the other project imports:

```python
from Dev.kb_chatbot.lexical import LexicalIndex
```

Then in `ingest()`, after the upsert loop completes and before `report.chunks_created = total` (line 94), insert:

```python
    # Build the BM25 sidecar from the COLLECTION (not just this batch) so the
    # lexical index always mirrors chroma exactly, even after partial re-ingests.
    stored = collection.get(include=["documents"])
    lexical = LexicalIndex.build(list(zip(stored["ids"], stored["documents"])))
    lexical.save(chroma_path / config.BM25_FILE)
    log.info("BM25 index: %d docs → %s", len(stored["ids"]), config.BM25_FILE)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_ingest_bm25.py -v`
Expected: 2 passed

- [ ] **Step 5: Run the full chatbot suite**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests -q`
Expected: 122 passed

- [ ] **Step 6: Commit**

```powershell
git add Dev/kb_chatbot/ingest.py Dev/kb_chatbot/config.py Dev/kb_chatbot/tests/test_ingest_bm25.py
git commit -m "feat(v3): ingest builds BM25 sidecar from chroma collection"
```

---

### Task 6: Hybrid `Retriever` — fusion before rerank, fallback on failure

**Files:**
- Modify: `Dev/kb_chatbot/retriever.py`
- Modify: `Dev/kb_chatbot/config.py` (toggles)
- Create: `Dev/kb_chatbot/tests/fixtures/tiny_library/web2/payments/err_7741_sweep.json`
- Test: `Dev/kb_chatbot/tests/test_hybrid_retriever.py`

- [ ] **Step 1: Add config toggles**

Add to `Dev/kb_chatbot/config.py` in the "Retrieval defaults" block (after `BM25_FILE`):

```python
HYBRID_BM25         = True           # BM25 + vector with RRF fusion
QUERY_EXPANSION     = True           # synonym expansion on the BM25 query
RRF_K               = 60
```

- [ ] **Step 2: Add a fixture article holding a rare exact token**

Create `Dev/kb_chatbot/tests/fixtures/tiny_library/web2/payments/err_7741_sweep.json`:

```json
{
  "space_key": "WEB2",
  "space_name": "Web2 Knowledge Base",
  "product": "web2",
  "title": "Resolving Sweep Error ERR-7741",
  "url": "http://example/web2/err-7741-sweep",
  "scraped_at": "2026-06-01T10:00:00",
  "screenshot": "tiny.png",
  "body_md": "# Resolving Sweep Error ERR-7741\n\n## Symptom\n\nA recurring payment sweep aborts and the journal shows code ERR-7741.\n\n## Cause\n\nThe nostro account mapping is missing for the settlement currency.\n\n## Fix\n\n1. Open Administration > Nostro Mapping.\n2. Add a mapping for the affected currency.\n3. Re-run the sweep batch.\n"
}
```

- [ ] **Step 3: Write the failing tests**

Create `Dev/kb_chatbot/tests/test_hybrid_retriever.py`:

```python
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot import config
from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters, RetrievalResult

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


@pytest.fixture(scope="module")
def chroma_dir():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))
    return Path(tmp)


@pytest.fixture(scope="module")
def hybrid(chroma_dir):
    r = Retriever(chroma_dir, confidence_floor=0.0)
    yield r
    r.close()


def test_lexical_index_loads_on_init(hybrid):
    assert hybrid.lexical is not None
    assert hybrid.lexical_warning is None


def test_exact_error_code_is_retrieved(hybrid):
    r = hybrid.retrieve("ERR-7741 sweep failure", Filters())
    assert isinstance(r, RetrievalResult)
    titles = [c.metadata["title"] for c in r.chunks]
    assert "Resolving Sweep Error ERR-7741" in titles


def test_product_filter_applies_to_lexical_results_too(hybrid):
    r = hybrid.retrieve("ERR-7741 sweep failure", Filters(product="saleshub"))
    assert all(c.metadata["product"] == "saleshub" for c in r.chunks)


def test_contract_unchanged_vector_only(chroma_dir):
    r = Retriever(chroma_dir, confidence_floor=0.0, use_bm25=False)
    try:
        res = r.retrieve("IBAN validation form", Filters())
        assert res.chunks and res.chunks[0].metadata["product"] == "saleshub"
        assert res.rerank_top_score != 0.0
    finally:
        r.close()


def test_abstains_on_junk_with_high_floor(chroma_dir):
    strict = Retriever(chroma_dir, confidence_floor=0.99)
    try:
        res = strict.retrieve("quantum field theory of cricket", Filters())
        assert res.abstain_reason == "no_relevant_kb_match"
        assert res.chunks == []
    finally:
        strict.close()


def test_missing_pickle_triggers_rebuild(chroma_dir):
    (chroma_dir / config.BM25_FILE).unlink()
    r = Retriever(chroma_dir, confidence_floor=0.0)
    try:
        assert r.lexical is not None              # rebuilt from chroma docs
        assert (chroma_dir / config.BM25_FILE).exists()  # re-persisted
        res = r.retrieve("ERR-7741", Filters())
        assert any("ERR-7741" in c.text for c in res.chunks)
    finally:
        r.close()


def test_results_capped_at_top_k_rerank(hybrid):
    r = hybrid.retrieve("payment processing", Filters())
    assert len(r.chunks) <= hybrid.top_k_rerank
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_hybrid_retriever.py -v`
Expected: FAIL — `AttributeError: 'Retriever' object has no attribute 'lexical'` (and `unexpected keyword argument 'use_bm25'`)

- [ ] **Step 5: Implement the hybrid retriever**

Replace `Dev/kb_chatbot/retriever.py` imports and `__init__`/`retrieve` as follows. New imports after the existing ones:

```python
from Dev.kb_chatbot.expansion import expand_query, load_synonyms
from Dev.kb_chatbot.fusion import rrf_fuse
from Dev.kb_chatbot.lexical import LexicalIndex, corpus_hash
```

New `__init__` (replaces lines 34–48):

```python
    def __init__(
        self,
        chroma_path: Path,
        *,
        top_k_retrieve: int = config.TOP_K_RETRIEVE,
        top_k_rerank: int = config.TOP_K_RERANK,
        confidence_floor: float = config.CONFIDENCE_FLOOR,
        use_bm25: bool = config.HYBRID_BM25,
        use_expansion: bool = config.QUERY_EXPANSION,
        reranker_model: str = config.RERANKER_MODEL,
    ):
        self.client = chromadb.PersistentClient(path=str(chroma_path))
        self.collection = self.client.get_or_create_collection(name=COLLECTION_NAME)
        self.embedder = SentenceTransformer(config.EMBED_MODEL)
        self.reranker = CrossEncoder(reranker_model)
        self.top_k_retrieve = top_k_retrieve
        self.top_k_rerank = top_k_rerank
        self.confidence_floor = confidence_floor
        self.use_bm25 = use_bm25
        self.use_expansion = use_expansion
        self.synonyms = load_synonyms(config.SYNONYMS_FILE) if use_expansion else []
        self.lexical: Optional[LexicalIndex] = None
        self.lexical_warning: Optional[str] = None
        if use_bm25:
            self._load_lexical(chroma_path)
```

Add the loader and id-fetch helpers after `_query_chroma`:

```python
    def _load_lexical(self, chroma_path: Path) -> None:
        """Load the BM25 sidecar; rebuild from chroma docs if missing/stale.
        On total failure fall back to vector-only and record a warning."""
        pkl = chroma_path / config.BM25_FILE
        try:
            current_ids = self.collection.get(include=[])["ids"]
            if pkl.exists():
                idx = LexicalIndex.load(pkl)
                if idx.hash == corpus_hash(current_ids):
                    self.lexical = idx
                    return
                log.info("BM25 index stale (corpus changed) — rebuilding")
            else:
                log.info("BM25 index missing — rebuilding from chroma")
            stored = self.collection.get(include=["documents"])
            idx = LexicalIndex.build(list(zip(stored["ids"], stored["documents"])))
            idx.save(pkl)
            self.lexical = idx
        except Exception as exc:
            log.exception("BM25 index unavailable — falling back to vector-only")
            self.lexical = None
            self.lexical_warning = f"Keyword search unavailable ({exc}); using vector search only."

    def _get_by_ids(self, ids: list[str]) -> dict[str, Chunk]:
        if not ids:
            return {}
        results = self.collection.get(ids=ids, include=["documents", "metadatas"])
        out: dict[str, Chunk] = {}
        for cid, doc, meta in zip(results["ids"], results["documents"], results["metadatas"]):
            out[cid] = Chunk(id=cid, text=doc, metadata=dict(meta or {}))
        return out
```

New `retrieve()` (replaces lines 70–95; the rerank + gate tail is byte-identical to v2.3 — the contract is untouched):

```python
    def retrieve(self, query: str, filters: Filters) -> RetrievalResult:
        query_vec = self._embed(query)
        vector_chunks = self._query_chroma(query_vec, filters, self.top_k_retrieve)
        chunk_map: dict[str, Chunk] = {c.id: c for c in vector_chunks}
        rankings: list[list[str]] = [[c.id for c in vector_chunks]]

        if self.lexical is not None:
            bm25_query = expand_query(query, self.synonyms) if self.synonyms else query
            lex_ids = self.lexical.query(bm25_query, self.top_k_retrieve)
            fetched = self._get_by_ids([i for i in lex_ids if i not in chunk_map])
            chunk_map.update(fetched)
            if filters.product:
                lex_ids = [
                    i for i in lex_ids
                    if i in chunk_map and chunk_map[i].metadata.get("product") == filters.product
                ]
            else:
                lex_ids = [i for i in lex_ids if i in chunk_map]
            if lex_ids:
                rankings.append(lex_ids)

        fused_ids = rrf_fuse(rankings, k=config.RRF_K)[: self.top_k_retrieve]
        candidates = [chunk_map[i] for i in fused_ids if i in chunk_map]
        if not candidates:
            return RetrievalResult(abstain_reason="no_relevant_kb_match")

        pairs = [(query, c.text) for c in candidates]
        scores = self.reranker.predict(pairs)
        scored = sorted(zip(candidates, scores), key=lambda t: t[1], reverse=True)
        top = scored[: self.top_k_rerank]
        top_score = float(top[0][1]) if top else 0.0

        if top_score < self.confidence_floor:
            log.info("Abstaining: top rerank score %.3f < floor %.3f", top_score, self.confidence_floor)
            return RetrievalResult(
                chunks=[],
                raw_top_score=0.0,
                rerank_top_score=top_score,
                abstain_reason="no_relevant_kb_match",
            )

        return RetrievalResult(
            chunks=[c for c, _ in top],
            raw_top_score=0.0,
            rerank_top_score=top_score,
        )
```

- [ ] **Step 6: Run new tests, then the full suite**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_hybrid_retriever.py -v`
Expected: 7 passed

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests -q`
Expected: 129 passed. **Watch for**: existing retriever/orchestrator/integration tests must pass untouched — they pin the citation/abstention contract. The fixture addition changes tiny_library counts; if `test_kb_*`/ingest count assertions fail, inspect and update only counts that legitimately grew by one article.

- [ ] **Step 7: Commit**

```powershell
git add Dev/kb_chatbot/retriever.py Dev/kb_chatbot/config.py Dev/kb_chatbot/tests/test_hybrid_retriever.py Dev/kb_chatbot/tests/fixtures/tiny_library/web2/payments/err_7741_sweep.json
git commit -m "feat(v3): hybrid BM25+vector retrieval with RRF fusion before rerank gate"
```

---

### Task 7: `eval/metrics.py` — scoring primitives

**Files:**
- Create: `Dev/kb_chatbot/eval/__init__.py` (empty)
- Create: `Dev/kb_chatbot/eval/metrics.py`
- Test: `Dev/kb_chatbot/tests/test_eval_metrics.py`

- [ ] **Step 1: Write the failing tests**

Create `Dev/kb_chatbot/tests/test_eval_metrics.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.eval.metrics import unique_article_urls, recall_at_k, mrr
from Dev.kb_chatbot.chunker import Chunk


def _chunk(url):
    return Chunk(id=url, text="t", metadata={"url": url})


def test_unique_article_urls_preserves_rank_order():
    chunks = [_chunk("u1"), _chunk("u2"), _chunk("u1"), _chunk("u3")]
    assert unique_article_urls(chunks) == ["u1", "u2", "u3"]


def test_recall_at_k_hit_and_miss():
    assert recall_at_k(["a", "b", "c"], expected=["b"], k=3) is True
    assert recall_at_k(["a", "b", "c"], expected=["z"], k=3) is False
    assert recall_at_k(["a", "b", "c"], expected=["c"], k=2) is False  # outside k


def test_recall_any_expected_counts():
    assert recall_at_k(["a"], expected=["z", "a"], k=1) is True


def test_mrr_reciprocal_rank_of_first_hit():
    assert mrr(["x", "a", "b"], expected=["a"]) == 0.5
    assert mrr(["a"], expected=["a"]) == 1.0
    assert mrr(["x", "y"], expected=["a"]) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_eval_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'Dev.kb_chatbot.eval'`

- [ ] **Step 3: Implement**

Create empty `Dev/kb_chatbot/eval/__init__.py`, then `Dev/kb_chatbot/eval/metrics.py`:

```python
"""Pure scoring functions for the retrieval eval harness."""
from __future__ import annotations

from Dev.kb_chatbot.chunker import Chunk


def unique_article_urls(chunks: list[Chunk]) -> list[str]:
    """Article-level ranking: unique chunk URLs in retrieval order."""
    seen: set[str] = set()
    out: list[str] = []
    for c in chunks:
        url = c.metadata.get("url", "")
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def recall_at_k(retrieved_urls: list[str], expected: list[str], k: int) -> bool:
    return any(url in expected for url in retrieved_urls[:k])


def mrr(retrieved_urls: list[str], expected: list[str]) -> float:
    for i, url in enumerate(retrieved_urls):
        if url in expected:
            return 1.0 / (i + 1)
    return 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_eval_metrics.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```powershell
git add Dev/kb_chatbot/eval/__init__.py Dev/kb_chatbot/eval/metrics.py Dev/kb_chatbot/tests/test_eval_metrics.py
git commit -m "feat(v3): eval metrics — recall@k, MRR, article-level url ranking"
```

---

### Task 8: Golden set — seed extraction + authored cases

**Files:**
- Create: `Dev/kb_chatbot/eval/seed_from_chats.py`
- Create: `Dev/kb_chatbot/eval/golden.jsonl`

**Spec correction (document in commit):** the spec says seeds come from `usage.jsonl`, but that file has no query text. Queries live in `chats/*.json` (user turns); the assistant turn that follows carries `citations`. Seed from chats instead.

- [ ] **Step 1: Write the seed extractor**

Create `Dev/kb_chatbot/eval/seed_from_chats.py`:

```python
"""Extract golden-set seed candidates from saved chat sessions.

Usage:
  python -m Dev.kb_chatbot.eval.seed_from_chats --chats <dir> [--out seeds.jsonl]

Each user turn followed by an assistant turn with verified citations becomes a
candidate: {"query": ..., "expected_urls": [...], "kind": "answerable"}.
Citations carry titles, not URLs, so expected_urls starts empty and is filled
by hand against library/kb (the seed output is a worksheet, not the gate)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def extract(chats_dir: Path) -> list[dict]:
    seeds: list[dict] = []
    for f in sorted(chats_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        turns = data.get("turns", [])
        for i, turn in enumerate(turns[:-1]):
            nxt = turns[i + 1]
            if turn.get("role") != "user" or nxt.get("role") != "assistant":
                continue
            citations = [c.get("raw", "") for c in (nxt.get("citations") or []) if c.get("verified")]
            if not citations:
                continue
            seeds.append({
                "query": turn.get("content", "").strip(),
                "cited_titles": sorted(set(citations)),
                "expected_urls": [],
                "kind": "answerable",
                "source": f.name,
            })
    return seeds


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chats", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "seeds.jsonl")
    args = ap.parse_args()
    seeds = extract(args.chats)
    with open(args.out, "w", encoding="utf-8") as fh:
        for s in seeds:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    print(f"{len(seeds)} seed candidates -> {args.out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the real chats**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m Dev.kb_chatbot.eval.seed_from_chats --chats "..\..\..\dist\chatbot_state\chats"`
Expected: `N seed candidates -> ...seeds.jsonl` (N ≈ 10–20). `seeds.jsonl` is a working file — do **not** commit it (add nothing; it is listed in step 5's .gitignore).

- [ ] **Step 3: Fill in seed URLs and author the full golden set**

Create `Dev/kb_chatbot/eval/golden.jsonl`. Format per line:

```json
{"query": "how do I book a corporate deal", "expected_urls": ["https://help.contoso.example/tradedesk/..."], "product": "tradedesk", "kind": "answerable"}
{"query": "what's the weather in toronto", "expected_urls": [], "product": null, "kind": "must_abstain"}
```

Authoring procedure (content work — read the real KB):

1. For each seed in `seeds.jsonl`, find the cited article's JSON under `..\..\..\library\kb\<product>\...`, copy its `url` into `expected_urls`, drop `cited_titles`/`source`, keep the user's original phrasing.
2. Author additional cases by reading actual articles under `..\..\..\library\kb` and writing questions a support user would ask, with that article's `url` as expected. Target distribution (≈95 total):

| product | answerable cases |
|---|---|
| tradedesk | 25 |
| saleshub | 25 |
| api | 10 |
| web2 | 10 |
| web4 | 10 |
| other | 5 |
| must_abstain (out-of-domain junk: weather, recipes, general IT, competitor products) | 10 |

3. For at least 15 of the answerable cases, phrase the query using a synonym the article does **not** contain (e.g. article says "book a deal", query says "post a trade") — these are the cases expansion exists for. Mark them with `"tag": "synonym"`.
4. For at least 10 cases, use paraphrases with zero keyword overlap beyond stop-words — these exercise the vector side. Mark with `"tag": "paraphrase"`.
5. `expected_urls` may list multiple URLs when several articles legitimately answer.

- [ ] **Step 4: Validate the golden set mechanically**

Run:
```powershell
& "..\..\..\scraper\venv\Scripts\python.exe" -c "
import json, pathlib
lines = [json.loads(l) for l in pathlib.Path('Dev/kb_chatbot/eval/golden.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
kinds = [l['kind'] for l in lines]
assert all(k in ('answerable','must_abstain') for k in kinds)
assert all(l['expected_urls'] for l in lines if l['kind']=='answerable'), 'answerable without expected_urls'
assert all(not l['expected_urls'] for l in lines if l['kind']=='must_abstain')
print(len(lines), 'cases —', kinds.count('answerable'), 'answerable,', kinds.count('must_abstain'), 'abstain')
"
```
Expected: `~95 cases — ~85 answerable, ~10 abstain`, no assertion errors.

- [ ] **Step 5: Ignore working files, commit golden set**

Create/append `.gitignore` entries at worktree root (`.gitignore`):

```
Dev/kb_chatbot/eval/seeds.jsonl
Dev/kb_chatbot/eval/workspace/
```

```powershell
git add Dev/kb_chatbot/eval/seed_from_chats.py Dev/kb_chatbot/eval/golden.jsonl .gitignore
git commit -m "feat(v3): golden eval set (seeded from real chats + authored cases)

Spec correction: queries seeded from chats/*.json, not usage.jsonl
(usage entries carry no query text)."
```

- [ ] **Step 6: CHECKPOINT — user spot-review**

Stop and ask the user to spot-review `golden.jsonl` before it becomes the gate. Do not proceed to Task 9 until approved.

---

### Task 9: `eval/run_eval.py` harness + committed baseline

**Files:**
- Create: `Dev/kb_chatbot/eval/run_eval.py`
- Create: `Dev/kb_chatbot/eval/results/` (committed results)

- [ ] **Step 1: Write the harness**

Create `Dev/kb_chatbot/eval/run_eval.py`:

```python
"""Retrieval eval harness. Dev-only — never bundled into the exe.

Usage:
  python -m Dev.kb_chatbot.eval.run_eval --chroma <dir> --label baseline \
      [--golden <path>] [--no-bm25] [--no-expansion] [--reranker <model>] [--floor <f>]

Metrics: recall@8 (article url in chunks handed to the LLM), MRR,
abstain precision/recall on must_abstain cases, p50/p95 latency.
Writes JSON to eval/results/<label>.json and prints a summary table."""
from __future__ import annotations
import argparse
import json
import statistics
import time
from pathlib import Path

from Dev.kb_chatbot import config
from Dev.kb_chatbot.eval.metrics import mrr, recall_at_k, unique_article_urls
from Dev.kb_chatbot.retriever import Filters, Retriever

HERE = Path(__file__).parent


def load_golden(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def run(retriever: Retriever, golden: list[dict], k: int) -> dict:
    rows, latencies = [], []
    for case in golden:
        t0 = time.perf_counter()
        result = retriever.retrieve(case["query"], Filters())
        ms = (time.perf_counter() - t0) * 1000
        latencies.append(ms)
        urls = unique_article_urls(result.chunks)
        rows.append({
            "query": case["query"],
            "kind": case["kind"],
            "tag": case.get("tag"),
            "abstained": result.abstain_reason is not None,
            "hit": recall_at_k(urls, case["expected_urls"], k) if case["kind"] == "answerable" else None,
            "mrr": mrr(urls, case["expected_urls"]) if case["kind"] == "answerable" else None,
            "rerank_top_score": result.rerank_top_score,
            "latency_ms": round(ms, 1),
        })
    answerable = [r for r in rows if r["kind"] == "answerable"]
    junk = [r for r in rows if r["kind"] == "must_abstain"]
    abstained_junk = sum(1 for r in junk if r["abstained"])
    abstained_ans = sum(1 for r in answerable if r["abstained"])
    return {
        "cases": len(rows),
        f"recall@{k}": round(sum(1 for r in answerable if r["hit"]) / max(len(answerable), 1), 4),
        "mrr": round(statistics.mean(r["mrr"] for r in answerable) if answerable else 0.0, 4),
        "abstain_recall_on_junk": round(abstained_junk / max(len(junk), 1), 4),
        "false_abstain_on_answerable": round(abstained_ans / max(len(answerable), 1), 4),
        "p50_latency_ms": round(statistics.median(latencies), 1),
        "p95_latency_ms": round(sorted(latencies)[int(0.95 * (len(latencies) - 1))], 1),
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chroma", type=Path, required=True)
    ap.add_argument("--golden", type=Path, default=HERE / "golden.jsonl")
    ap.add_argument("--label", required=True)
    ap.add_argument("--k", type=int, default=config.TOP_K_RERANK)
    ap.add_argument("--no-bm25", action="store_true")
    ap.add_argument("--no-expansion", action="store_true")
    ap.add_argument("--reranker", default=config.RERANKER_MODEL)
    ap.add_argument("--floor", type=float, default=config.CONFIDENCE_FLOOR)
    args = ap.parse_args()

    retriever = Retriever(
        args.chroma,
        confidence_floor=args.floor,
        use_bm25=not args.no_bm25,
        use_expansion=not args.no_expansion,
        reranker_model=args.reranker,
    )
    try:
        summary = run(retriever, load_golden(args.golden), args.k)
    finally:
        retriever.close()

    summary["config"] = {
        "bm25": not args.no_bm25, "expansion": not args.no_expansion,
        "reranker": args.reranker, "floor": args.floor, "k": args.k,
    }
    out = HERE / "results" / f"{args.label}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    for key in (f"recall@{args.k}", "mrr", "abstain_recall_on_junk",
                "false_abstain_on_answerable", "p50_latency_ms", "p95_latency_ms"):
        print(f"{key:32s} {summary[key]}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Build the eval chroma workspace (current chunking, full library)**

Run:
```powershell
& "..\..\..\scraper\venv\Scripts\python.exe" -c "
from pathlib import Path
from Dev.kb_chatbot.ingest import ingest
r = ingest(Path('../../../library/kb'), Path('Dev/kb_chatbot/eval/workspace/chroma-main'))
print(r.articles_seen, 'articles', r.chunks_created, 'chunks', f'{r.duration_s:.0f}s')
"
```
Expected: ~1475 articles, several thousand chunks. (Workspace is gitignored.)

- [ ] **Step 3: Run the v2.3 baseline (all new stages OFF)**

Run:
```powershell
& "..\..\..\scraper\venv\Scripts\python.exe" -m Dev.kb_chatbot.eval.run_eval --chroma Dev/kb_chatbot/eval/workspace/chroma-main --label baseline-v2.3 --no-bm25 --no-expansion
```
Expected: metrics print; `eval/results/baseline-v2.3.json` written. **This number is the gate for everything after.**

- [ ] **Step 4: Run hybrid + expansion (current reranker)**

Run:
```powershell
& "..\..\..\scraper\venv\Scripts\python.exe" -m Dev.kb_chatbot.eval.run_eval --chroma Dev/kb_chatbot/eval/workspace/chroma-main --label hybrid-msmarco
```
Expected: recall@8 ≥ baseline. If it regresses, STOP — debug fusion before proceeding (superpowers:systematic-debugging).

- [ ] **Step 5: Commit harness + both result files**

```powershell
git add Dev/kb_chatbot/eval/run_eval.py Dev/kb_chatbot/eval/results/baseline-v2.3.json Dev/kb_chatbot/eval/results/hybrid-msmarco.json
git commit -m "feat(v3): eval harness; baseline + hybrid results on golden set"
```

---

### Task 10: Reranker benchmark, selection, floor recalibration

**Files:**
- Create: `Dev/kb_chatbot/eval/calibrate_floor.py`
- Modify: `Dev/kb_chatbot/config.py` (RERANKER_MODEL, CONFIDENCE_FLOOR)

- [ ] **Step 1: Benchmark candidate rerankers** (network needed once to download; cached afterward)

Run each (expect several minutes apiece — CrossEncoder over ~95 queries × 30 candidates):
```powershell
& "..\..\..\scraper\venv\Scripts\python.exe" -m Dev.kb_chatbot.eval.run_eval --chroma Dev/kb_chatbot/eval/workspace/chroma-main --label rerank-bge-base --reranker BAAI/bge-reranker-base --floor -99
& "..\..\..\scraper\venv\Scripts\python.exe" -m Dev.kb_chatbot.eval.run_eval --chroma Dev/kb_chatbot/eval/workspace/chroma-main --label rerank-bge-large --reranker BAAI/bge-reranker-large --floor -99
& "..\..\..\scraper\venv\Scripts\python.exe" -m Dev.kb_chatbot.eval.run_eval --chroma Dev/kb_chatbot/eval/workspace/chroma-main --label rerank-bge-v2-m3 --reranker BAAI/bge-reranker-v2-m3 --floor -99
```
(`--floor -99` disables the gate so pure ranking quality is measured; floors are recalibrated per-model in step 3.)

- [ ] **Step 2: Select the winner**

Decision rule (per approved design, accuracy at any cost): highest recall@8; ties broken by MRR, then by smaller model. Record all four results (incl. `hybrid-msmarco`) in a comparison table in the commit message.

- [ ] **Step 3: Write and run the floor calibrator**

Create `Dev/kb_chatbot/eval/calibrate_floor.py`:

```python
"""Pick CONFIDENCE_FLOOR for a reranker from a no-gate eval results file.

Usage:
  python -m Dev.kb_chatbot.eval.calibrate_floor --results eval/results/rerank-bge-large.json

Sweeps thresholds over observed rerank_top_score values; recommends the floor
maximizing F1 of 'abstain on junk' (positive class = must_abstain abstained,
false positive = answerable abstained)."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def best_floor(rows: list[dict]) -> tuple[float, float]:
    answerable = [r["rerank_top_score"] for r in rows if r["kind"] == "answerable"]
    junk = [r["rerank_top_score"] for r in rows if r["kind"] == "must_abstain"]
    candidates = sorted(set(answerable + junk))
    best = (float("-inf"), 0.0)  # (floor, f1)
    for t in candidates:
        tp = sum(1 for s in junk if s < t)          # junk correctly gated
        fp = sum(1 for s in answerable if s < t)    # answerable wrongly gated
        fn = len(junk) - tp
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)
        if f1 > best[1]:
            best = (t, f1)
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True)
    args = ap.parse_args()
    rows = json.loads(args.results.read_text(encoding="utf-8"))["rows"]
    floor, f1 = best_floor(rows)
    print(f"recommended CONFIDENCE_FLOOR = {floor:.4f}  (abstain F1 = {f1:.3f})")


if __name__ == "__main__":
    main()
```

Run it on the winner's results file, e.g.:
```powershell
& "..\..\..\scraper\venv\Scripts\python.exe" -m Dev.kb_chatbot.eval.calibrate_floor --results Dev/kb_chatbot/eval/results/rerank-bge-large.json
```

- [ ] **Step 4: Update config and confirm with a gated run**

In `Dev/kb_chatbot/config.py` set `RERANKER_MODEL` to the winning model id and `CONFIDENCE_FLOOR` to the recommended value (round sensibly). Then:

```powershell
& "..\..\..\scraper\venv\Scripts\python.exe" -m Dev.kb_chatbot.eval.run_eval --chroma Dev/kb_chatbot/eval/workspace/chroma-main --label final-reranker-gated
```
Expected: recall@8 ≥ `hybrid-msmarco`; `abstain_recall_on_junk` ≥ 0.8; `false_abstain_on_answerable` ≤ 0.05.

- [ ] **Step 5: Run the full test suite** (floor/reranker change affects gate tests)

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests -q`
Expected: all pass. Tests constructing `Retriever(confidence_floor=0.99)` against bge logits (unbounded, not 0–1) may need their floor literal raised (e.g. `99.0`) — that is a test-fixture adjustment, not a contract change; keep assertions identical.

- [ ] **Step 6: Commit**

```powershell
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/eval/calibrate_floor.py Dev/kb_chatbot/eval/results/ Dev/kb_chatbot/tests
git commit -m "feat(v3): adopt <winner> reranker, recalibrated confidence floor (results table in body)"
```

---

### Task 11: Chunk overlap variant — measure, adopt or document

**Files:**
- Modify: `Dev/kb_chatbot/chunker.py`
- Modify: `Dev/kb_chatbot/config.py` (`CHUNK_OVERLAP_WORDS`)
- Test: `Dev/kb_chatbot/tests/test_chunker_overlap.py`

- [ ] **Step 1: Write the failing tests**

Create `Dev/kb_chatbot/tests/test_chunker_overlap.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chunker import _split_body_md

LONG = "# T\n\n## A\n\n" + " ".join(f"w{i}" for i in range(600)) + "\n\n## B\n\nshort tail."


def test_zero_overlap_is_default_and_unchanged():
    assert _split_body_md(LONG) == _split_body_md(LONG, overlap_words=0)


def test_overlap_prepends_tail_of_previous_chunk():
    chunks = _split_body_md(LONG, target_words=200, overlap_words=30)
    assert len(chunks) >= 2
    prev_tail = " ".join(chunks[0].split()[-30:])
    assert chunks[1].startswith("[…] ")
    assert " ".join(chunks[1].split()[1:31]) == prev_tail


def test_single_chunk_documents_get_no_overlap_marker():
    chunks = _split_body_md("# T\n\nshort body.", overlap_words=50)
    assert len(chunks) == 1 and "[…]" not in chunks[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_chunker_overlap.py -v`
Expected: FAIL — `unexpected keyword argument 'overlap_words'`

- [ ] **Step 3: Implement**

Add to `Dev/kb_chatbot/config.py` retrieval block: `CHUNK_OVERLAP_WORDS  = 0`.

In `Dev/kb_chatbot/chunker.py`, change `_split_body_md`'s signature to:

```python
def _split_body_md(body_md: str, target_words: int = config.CHUNK_TARGET_WORDS,
                   overlap_words: int = config.CHUNK_OVERLAP_WORDS) -> list[str]:
```

and append before its `return chunks`:

```python
    if overlap_words > 0 and len(chunks) > 1:
        overlapped = [chunks[0]]
        for prev, cur in zip(chunks, chunks[1:]):
            tail = " ".join(prev.split()[-overlap_words:])
            overlapped.append(f"[…] {tail}\n\n{cur}")
        chunks = overlapped
```

Thread the param through `build_article_chunks` (signature gains `overlap_words: int = config.CHUNK_OVERLAP_WORDS`, passes it to `_split_body_md`) and through `ingest()` (signature gains `overlap_words: int = config.CHUNK_OVERLAP_WORDS`, passes to `build_article_chunks`).

- [ ] **Step 4: Run tests, then full suite**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_chunker_overlap.py Dev/kb_chatbot/tests -q`
Expected: all pass (default 0 = byte-identical chunking).

- [ ] **Step 5: Ingest the overlap variant and measure**

```powershell
& "..\..\..\scraper\venv\Scripts\python.exe" -c "
from pathlib import Path
from Dev.kb_chatbot.ingest import ingest
r = ingest(Path('../../../library/kb'), Path('Dev/kb_chatbot/eval/workspace/chroma-overlap80'), overlap_words=80)
print(r.chunks_created, 'chunks')
"
& "..\..\..\scraper\venv\Scripts\python.exe" -m Dev.kb_chatbot.eval.run_eval --chroma Dev/kb_chatbot/eval/workspace/chroma-overlap80 --label chunk-overlap80
```

- [ ] **Step 6: Adopt or document**

Decision rule: set `CHUNK_OVERLAP_WORDS = 80` in config **only if** `chunk-overlap80` recall@8 > `final-reranker-gated` recall@8. Otherwise leave 0 — the results file documents why.

- [ ] **Step 7: Commit**

```powershell
git add Dev/kb_chatbot/chunker.py Dev/kb_chatbot/ingest.py Dev/kb_chatbot/config.py Dev/kb_chatbot/tests/test_chunker_overlap.py Dev/kb_chatbot/eval/results/chunk-overlap80.json
git commit -m "feat(v3): optional chunk overlap; adopted/declined per golden-set result"
```

---

### Task 12: Beta identity — version, state dir, title, lexical warning

**Files:**
- Modify: `Dev/kb_chatbot/config.py` (lines 6–12 region)
- Modify: `Dev/kb_chatbot/gui.py` (lines 190, 473–478)
- Test: `Dev/kb_chatbot/tests/test_beta_identity.py`

- [ ] **Step 1: Write the failing test**

Create `Dev/kb_chatbot/tests/test_beta_identity.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config


def test_beta_constants():
    assert config.IS_BETA is True
    assert config.APP_VERSION == "3.0.0-beta"
    assert config.window_title() == "Contoso KB Chatbot — v3.0 BETA"


def test_frozen_state_dir_name_is_beta():
    # The frozen branch must derive its state dir from STATE_DIR_NAME
    assert config.STATE_DIR_NAME == "chatbot_state_beta"


def test_dev_state_dir_unchanged():
    # Non-frozen (test) runs keep using Dev/kb_chatbot/state — never the beta dir
    assert config.STATE_DIR.name == "state"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_beta_identity.py -v`
Expected: FAIL — `AttributeError: ... no attribute 'IS_BETA'`

- [ ] **Step 3: Implement**

In `Dev/kb_chatbot/config.py`, replace lines 6–12 with:

```python
# ── Version / beta identity ───────────────────────────────────────────────────
APP_VERSION = "3.0.0-beta"
IS_BETA     = True
STATE_DIR_NAME = "chatbot_state_beta" if IS_BETA else "chatbot_state"


def window_title() -> str:
    return "Contoso KB Chatbot — v3.0 BETA" if IS_BETA else "Contoso KB Chatbot"


# ── Freeze-aware base paths ───────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent              # dist/ at runtime
    STATE_DIR = BASE_DIR / STATE_DIR_NAME
else:
    BASE_DIR = Path(__file__).parent.parent.parent      # Knowledge Base/
    STATE_DIR = Path(__file__).parent / "state"
```

In `Dev/kb_chatbot/gui.py` line 190, replace:

```python
        self.setWindowTitle("Contoso KB Chatbot")
```
with:
```python
        self.setWindowTitle(config.window_title())
```

In `gui.py` `_on_init_ready` (line 473), surface the lexical fallback warning — replace the body with:

```python
    @Slot(object)
    def _on_init_ready(self, retriever):
        self._retriever = retriever
        self.send_btn.setText("Send")
        self._set_chat_enabled(True)
        warning = getattr(retriever, "lexical_warning", None)
        if warning:
            self.statusBar().showMessage(f"⚠ {warning}")
            self._append("system", f"Warning: {warning}", "#e65100", "SYSTEM:")
        else:
            self.statusBar().showMessage("Ready")
        self._append("system", "Ready. Type a question below.", "#1b5e20", "SYSTEM:")
```

- [ ] **Step 4: Run tests, then full suite**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests/test_beta_identity.py Dev/kb_chatbot/tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/gui.py Dev/kb_chatbot/tests/test_beta_identity.py
git commit -m "feat(v3): beta identity — version constant, beta state dir, title, lexical warning surfacing"
```

---

### Task 13: Beta packaging — spec, build script, bundled models

**Files:**
- Create: `ContosoKBChatbot-BETA.spec`
- Create: `build_chatbot_beta_exe.bat`
- Modify: `Dev/kb_chatbot/config.py` (frozen model paths)

- [ ] **Step 1: Frozen model-path resolution in config**

In `Dev/kb_chatbot/config.py`, replace the two model constant lines (22–23) with:

```python
# ── Model defaults ────────────────────────────────────────────────────────────
_EMBED_REPO    = "sentence-transformers/all-MiniLM-L6-v2"
_RERANKER_REPO = RERANKER_MODEL_REPO = "BAAI/bge-reranker-large"  # set by Task 10 winner


def _model_path(repo: str) -> str:
    """Frozen builds bundle model snapshots under <_MEIPASS>/models/<repo-with-dashes>;
    dev runs (and a frozen build missing the bundle) use the HF cache by repo id."""
    if getattr(sys, "frozen", False):
        local = Path(getattr(sys, "_MEIPASS", ".")) / "models" / repo.replace("/", "--")
        if local.exists():
            return str(local)
    return repo


EMBED_MODEL    = _model_path(_EMBED_REPO)
RERANKER_MODEL = _model_path(_RERANKER_REPO)
```

(Substitute the actual Task 10 winner for `BAAI/bge-reranker-large` if different. `RERANKER_MODEL_REPO` keeps the repo id available to the .spec.)

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest Dev/kb_chatbot/tests -q`
Expected: all pass (dev path resolves to repo ids exactly as before).

- [ ] **Step 2: Write the beta spec**

Create `ContosoKBChatbot-BETA.spec`:

```python
# -*- mode: python ; coding: utf-8 -*-
# BETA build: separate exe name, bundles model weights + synonyms data.
# Never reuse for the stable build — stable spec is ContosoKBChatbot.spec.
from PyInstaller.utils.hooks import collect_all
from huggingface_hub import snapshot_download

datas, binaries, hiddenimports = [], [], []
for pkg in ("PySide6", "sentence_transformers", "chromadb", "claude_agent_sdk", "markdown"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

hiddenimports += [
    "torch", "transformers", "tokenizers",
    "sklearn.utils._cython_blas",
    "rank_bm25",
]

# Bundle model snapshots from the local HF cache (must be pre-downloaded —
# Task 10 benchmarking does that). local_files_only keeps the build offline.
import sys as _sys
_sys.path.insert(0, ".")
from Dev.kb_chatbot.config import _EMBED_REPO, RERANKER_MODEL_REPO
for repo in (_EMBED_REPO, RERANKER_MODEL_REPO):
    snap = snapshot_download(repo, local_files_only=True)
    datas.append((snap, "models/" + repo.replace("/", "--")))

# Synonyms + any future bundled data
datas.append(("Dev/kb_chatbot/data", "kb_chatbot_data"))

a = Analysis(
    ["Dev/kb_chatbot/gui.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # NOTE: do NOT exclude torch submodules — torch imports them eagerly
        # at startup. Only torchvision/torchaudio are safe to exclude.
        "torchvision", "torchaudio",
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic", "PySide6.Qt3DExtras", "PySide6.Qt3DAnimation",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="ContosoKBChatbot-BETA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
```

- [ ] **Step 3: Write the build script**

Create `build_chatbot_beta_exe.bat`:

```bat
@echo off
setlocal
pushd "%~dp0"
REM Output goes to the MAIN checkout's dist\ (three levels up from this worktree).
REM Stable ContosoKBChatbot.exe is never touched: different output name, and
REM PyInstaller --clean only clears its own build cache, not dist contents.
set DIST_DIR=%~dp0..\..\..\dist
echo Building ContosoKBChatbot-BETA.exe into %DIST_DIR% ...
"%~dp0..\..\..\scraper\venv\Scripts\python.exe" -m PyInstaller ContosoKBChatbot-BETA.spec --distpath "%DIST_DIR%" --workpath build_beta --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] Beta build failed.
    pause
    exit /b 1
)
echo.
echo Build complete. Artifact: %DIST_DIR%\ContosoKBChatbot-BETA.exe
pause
popd
endlocal
```

Also append `build_beta/` to the worktree `.gitignore`.

- [ ] **Step 4: Record dist state, build, verify nothing overwritten**

```powershell
Get-ChildItem "..\..\..\dist" -File | Select-Object Name, Length, LastWriteTime | Out-File dist-before.txt -Encoding utf8
cmd /c build_chatbot_beta_exe.bat   # remove `pause` lines first if running non-interactively
Get-ChildItem "..\..\..\dist" -File | Select-Object Name, Length, LastWriteTime
```
Expected: `ContosoKBChatbot-BETA.exe` new (likely 1.5–2.5 GB with bundled bge weights); `ContosoKBChatbot.exe` and `ContosoKBScraper.exe` byte-identical timestamps to `dist-before.txt`. Delete `dist-before.txt` after checking.

- [ ] **Step 5: Smoke-test the beta exe**

Launch `..\..\..\dist\ContosoKBChatbot-BETA.exe` and verify:
1. Window title reads "Contoso KB Chatbot — v3.0 BETA".
2. `dist\chatbot_state_beta\` is created; `dist\chatbot_state\` untouched (check LastWriteTime).
3. Run Reindex against `dist\library\kb`; ask "How do I create a corporate deal?" → answer with verified citation.
4. Ask an out-of-domain question → abstains.
5. Confirm first-launch extraction delay is tolerable (onefile unpacks ~2 GB; report the measured time).

- [ ] **Step 6: Commit**

```powershell
git add ContosoKBChatbot-BETA.spec build_chatbot_beta_exe.bat Dev/kb_chatbot/config.py .gitignore
git commit -m "feat(v3): beta packaging — separate exe, bundled models, isolated state dir"
```

---

### Task 14: Final verification + results summary

**Files:**
- Create: `Dev/kb_chatbot/eval/results/SUMMARY.md`

- [ ] **Step 1: Full test suite**

Run: `& "..\..\..\scraper\venv\Scripts\python.exe" -m pytest tests Dev/kb_chatbot/tests -q`
Expected: all pass (baseline 144 + ~25 new).

- [ ] **Step 2: Final eval run (shipped configuration)**

```powershell
& "..\..\..\scraper\venv\Scripts\python.exe" -m Dev.kb_chatbot.eval.run_eval --chroma Dev/kb_chatbot/eval/workspace/chroma-main --label final-shipped
```
(Use the overlap variant chroma instead if Task 11 adopted overlap.)

- [ ] **Step 3: Write the summary table**

Create `Dev/kb_chatbot/eval/results/SUMMARY.md` with the actual numbers from the result JSONs:

```markdown
# v3 Retrieval Overhaul — Golden Set Results

Golden set: NN cases (NN answerable, NN must-abstain). recall@8 = expected
article among chunks handed to the LLM.

| run | recall@8 | MRR | abstain recall (junk) | false abstain | p50 ms | p95 ms |
|---|---|---|---|---|---|---|
| baseline-v2.3 (vector + ms-marco) | | | | | | |
| hybrid-msmarco (+BM25 +expansion) | | | | | | |
| rerank-bge-base | | | | | | |
| rerank-bge-large | | | | | | |
| rerank-bge-v2-m3 | | | | | | |
| chunk-overlap80 | | | | | | |
| **final-shipped** | | | | | | |

Shipped config: reranker=<winner>, floor=<value>, overlap=<0 or 80>, RRF k=60.
```

Fill every cell from the committed result JSONs — no blanks may remain at commit time.

- [ ] **Step 4: Commit and report**

```powershell
git add Dev/kb_chatbot/eval/results/
git commit -m "docs(v3): golden-set results summary — baseline vs shipped"
```

Then report to the user: final numbers vs baseline, exe size, smoke-test outcome — and hand off to superpowers:finishing-a-development-branch.

---

## Self-review notes (already applied)

- **Spec coverage:** hybrid (T2/T3/T6), expansion (T4), reranker (T10), golden set (T7–T9), chunk tuning (T11), beta identity/packaging (T12/T13), error handling rows (T6 fallback, T4 malformed YAML, T12 warning surfacing, preflight unchanged), constraints (contract tests in T6, offline bundling in T13).
- **Spec corrections discovered during planning:** (1) golden-set seeds come from `chats/*.json`, not `usage.jsonl` — documented in Task 8; (2) v2.4 merged to master on 2026-06-05 and its branch was deleted — v3 still builds on v2.3 per the approved decision.
- **Type consistency:** `LexicalIndex.build/query/save/load/.ids/.hash`, `rrf_fuse(rankings, k)`, `load_synonyms→list[list[str]]`, `expand_query(query, groups)`, `Retriever(use_bm25, use_expansion, reranker_model)`, `lexical_warning` — names match across all tasks.
