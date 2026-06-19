import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters, RetrievalResult

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


@pytest.fixture(scope="module")
def retriever():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))
    yield Retriever(Path(tmp), confidence_floor=0.0)


def test_retrieve_returns_chunks_relevant_to_iban(retriever):
    r = retriever.retrieve("IBAN validation form", Filters())
    assert isinstance(r, RetrievalResult)
    assert len(r.chunks) > 0
    assert r.chunks[0].metadata["product"] == "saleshub"


def test_filter_by_product_works_for_each_of_six(retriever):
    for prod in ("api", "tradedesk", "saleshub", "web2", "web4", "other"):
        r = retriever.retrieve("anything", Filters(product=prod))
        assert all(c.metadata["product"] == prod for c in r.chunks)


def test_retrieve_returns_top_k_max(retriever):
    r = retriever.retrieve("how do I do this", Filters())
    assert len(r.chunks) <= retriever.top_k_rerank


def test_retrieve_quick_returns_top_k_no_rerank(retriever):
    r = retriever.retrieve_quick("payment", limit=5)
    assert len(r) <= 5
    assert all("product" in c.metadata for c in r)


def test_confidence_gate_triggers_for_unrelated_query():
    with tempfile.TemporaryDirectory() as tmp:
        ingest(FIX, Path(tmp))
        strict = Retriever(Path(tmp), confidence_floor=0.99)
        try:
            r = strict.retrieve("quantum field theory", Filters())
            assert r.abstain_reason == "no_relevant_kb_match"
            assert r.chunks == []
        finally:
            strict.close()


def test_looks_like_error():
    from Dev.kb_chatbot.chat.orchestrator import _looks_like_error
    assert _looks_like_error("GetWebDeal returns a null buy amount error")
    assert _looks_like_error("the drawdown margin is duplicated incorrectly")
    assert not _looks_like_error("how do I book a spot deal")
