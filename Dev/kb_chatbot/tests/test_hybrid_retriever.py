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


def test_product_filter_includes_matching_and_excludes_wrong_product(hybrid):
    # The ERR-7741 article is a web2 doc with a strong, distinctive BM25 hit.
    # With product=web2 it must come through; with product=saleshub it must be
    # filtered out of the BM25 lane entirely (and no web2 chunk may leak).
    in_web2 = hybrid.retrieve("ERR-7741 sweep failure", Filters(product="web2"))
    assert in_web2.chunks, "expected the web2 ERR-7741 article to be retrieved"
    assert "Resolving Sweep Error ERR-7741" in [c.metadata["title"] for c in in_web2.chunks]
    assert all(c.metadata["product"] == "web2" for c in in_web2.chunks)

    in_sales = hybrid.retrieve("ERR-7741 sweep failure", Filters(product="saleshub"))
    assert all(c.metadata["product"] == "saleshub" for c in in_sales.chunks)
    assert "Resolving Sweep Error ERR-7741" not in [c.metadata["title"] for c in in_sales.chunks]


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


def test_reranks_full_union_not_truncated_to_top_k_retrieve(chroma_dir):
    # Regression: the fused union of vector+BM25 lanes must ALL reach the
    # reranker. With a tiny top_k_retrieve the union exceeds it; truncating the
    # fused list pre-rerank would silently drop candidates a lane surfaced
    # (this measurably dropped recall on the golden set).
    r = Retriever(chroma_dir, confidence_floor=0.0, top_k_retrieve=2)
    try:
        seen: dict[str, int] = {}
        orig = r.reranker.predict

        def spy(pairs, *a, **k):
            seen["n"] = len(pairs)
            return orig(pairs, *a, **k)

        r.reranker.predict = spy
        # A query spanning several distinct fixture docs across both lanes so
        # the vector top-2 and BM25 top-2 don't collapse to the same 2 ids.
        r.retrieve("ERR-7741 corporate deal IBAN form recurring payment", Filters())
        assert seen["n"] > 2  # union reranked, not truncated back to top_k_retrieve=2
    finally:
        r.close()
