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
