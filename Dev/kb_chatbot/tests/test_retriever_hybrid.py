import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters
from Dev.kb_chatbot.chunker import Chunk

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


@pytest.fixture(scope="module")
def retriever():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))
    yield Retriever(Path(tmp), confidence_floor=0.0)


def test_rrf_fuse_ranks_shared_doc_first_and_is_deterministic(retriever):
    a = Chunk(id="a", text="", metadata={})
    b = Chunk(id="b", text="", metadata={})
    c = Chunk(id="c", text="", metadata={})
    vec = [a, b]      # a rank0, b rank1
    bm = [b, c]       # b rank0, c rank1
    fused = [x.id for x in retriever._rrf_fuse(vec, bm, k=60)]
    assert fused[0] == "b"                       # in both lists -> highest fused score
    assert set(fused) == {"a", "b", "c"}
    assert [x.id for x in retriever._rrf_fuse(vec, bm, k=60)] == fused  # deterministic


def test_bm25_candidates_returns_list(retriever):
    cands = retriever._bm25_candidates("payment", Filters(), 10)
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
    retriever.invalidate_bm25()
    assert retriever._bm25 is None
    assert retriever._bm25_ids == []
