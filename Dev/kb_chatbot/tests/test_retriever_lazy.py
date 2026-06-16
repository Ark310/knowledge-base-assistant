import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import numpy as np
import Dev.kb_chatbot.retriever as r


class _FakeST:
    def __init__(self, *a, **k):
        pass
    def encode(self, text, **k):
        return np.zeros(384)


def test_reranker_is_lazy(monkeypatch, tmp_path):
    calls = {"n": 0}

    class _FakeCE:
        def __init__(self, *a, **k):
            calls["n"] += 1
        def predict(self, pairs):
            return [0.0] * len(pairs)

    monkeypatch.setattr(r, "SentenceTransformer", _FakeST)
    monkeypatch.setattr(r, "CrossEncoder", _FakeCE)
    rt = r.Retriever(tmp_path / "chroma")
    assert rt._reranker is None        # not loaded at construction
    assert calls["n"] == 0
    rt._get_reranker()
    assert calls["n"] == 1             # loaded on first use
    rt._get_reranker()
    assert calls["n"] == 1             # cached afterwards


def test_retriever_uses_provided_embedder(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "CrossEncoder", lambda *a, **k: None)
    sentinel = _FakeST()
    rt = r.Retriever(tmp_path / "chroma", embedder=sentinel)
    assert rt.embedder is sentinel


def test_get_by_ids_and_ticket_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "CrossEncoder", lambda *a, **k: None)
    monkeypatch.setattr(r, "SentenceTransformer", _FakeST)
    rt = r.Retriever(tmp_path / "chroma")
    rt.collection.upsert(
        ids=["a", "b"],
        embeddings=[[0.0] * 384, [0.1] * 384],
        documents=["doc a", "doc b"],
        metadatas=[{"ticket_id": "100", "kind": "ticket"},
                   {"ticket_id": "200", "kind": "ticket"}],
    )
    assert rt.get_by_ids([]) == []
    assert [c.id for c in rt.get_by_ids(["a"])] == ["a"]
    assert [c.id for c in rt.get_by_ids(["a", "zzz"])] == ["a"]   # stale id silently dropped
    one = rt.get_by_ticket_ids(["100"])           # single -> where {ticket_id: v}
    assert len(one) == 1 and one[0].id == "a"
    two = rt.get_by_ticket_ids(["100", "200"])    # multi -> $in branch
    assert {c.id for c in two} == {"a", "b"}
    assert rt.get_by_ticket_ids([]) == []
