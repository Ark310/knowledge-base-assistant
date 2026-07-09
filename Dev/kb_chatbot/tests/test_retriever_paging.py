"""bug-171: a >32k-chunk collection blew SQLite's bound-variable limit.

ChromaDB binds one SQL variable per row/id, and modern SQLite caps that at
32766, so an unpaged collection.get() over a big corpus raised
"too many SQL variables" -- which surfaced to the user as
"Error executing plan: Internal error: ... too many SQL variables" and, because
retrieval throws before the answer is produced, the turn failed and its answer
was never saved. FakeCollection below models that cap so these tests fail
against an unpaged get() and pass once every get() is paged/batched.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.retriever import Retriever, _GET_BATCH


class FakeCollection:
    """Mimics ChromaDB's get() including the SQLite bound-variable ceiling."""
    CAP = 32766

    def __init__(self, n: int):
        self._ids = [f"c{i}" for i in range(n)]
        self._docs = [f"document body {i}" for i in range(n)]
        self._metas = [{"product": "tradedesk", "ticket_id": str(i)} for i in range(n)]
        self._by_id = {cid: i for i, cid in enumerate(self._ids)}

    def count(self):
        return len(self._ids)

    def _pack(self, idxs):
        return {"ids": [self._ids[i] for i in idxs],
                "documents": [self._docs[i] for i in idxs],
                "metadatas": [self._metas[i] for i in idxs]}

    def get(self, ids=None, where=None, include=None, limit=None, offset=None):
        if ids is not None:
            if len(ids) > self.CAP:
                raise RuntimeError("too many SQL variables")
            return self._pack([self._by_id[c] for c in ids if c in self._by_id])
        if where is not None:
            tid = where.get("ticket_id")
            wanted = tid["$in"] if isinstance(tid, dict) else [tid]
            if len(wanted) > self.CAP:
                raise RuntimeError("too many SQL variables")
            keep = [i for i, m in enumerate(self._metas) if m["ticket_id"] in set(wanted)]
            return self._pack(keep)
        # full scan: allowed only when paged under the cap
        n = len(self._ids)
        start = offset or 0
        end = n if limit is None else min(n, start + limit)
        if limit is None and n > self.CAP:
            raise RuntimeError("too many SQL variables")
        return self._pack(list(range(start, end)))


def _retriever_with(collection) -> Retriever:
    r = Retriever.__new__(Retriever)          # bypass __init__ (no real client / embedder)
    r.collection = collection
    return r


def test_get_all_pages_a_collection_larger_than_the_sqlite_cap():
    n = 38540  # the real reindexed corpus size that triggered the bug
    r = _retriever_with(FakeCollection(n))
    got = r._get_all()
    assert len(got["ids"]) == n
    assert len(got["documents"]) == n and len(got["metadatas"]) == n


def test_get_by_ids_batches_a_large_id_list():
    r = _retriever_with(FakeCollection(40000))
    ids = [f"c{i}" for i in range(40000)]      # far over CAP -> must be batched
    chunks = r.get_by_ids(ids)
    assert len(chunks) == 40000


def test_get_by_ticket_ids_batches_a_large_in_list():
    r = _retriever_with(FakeCollection(40000))
    tids = [str(i) for i in range(40000)]
    chunks = r.get_by_ticket_ids(tids)
    assert len(chunks) == 40000


def test_batch_size_is_under_the_sqlite_cap():
    assert _GET_BATCH <= FakeCollection.CAP


def test_unpaged_full_get_would_raise_proving_the_fake_models_the_cap():
    # Guards the test itself: without paging, the old code path raises.
    with pytest.raises(RuntimeError, match="too many SQL variables"):
        FakeCollection(38540).get(include=["documents", "metadatas"])
