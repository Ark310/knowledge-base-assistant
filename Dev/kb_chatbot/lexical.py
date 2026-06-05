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
        # Safe: pickle file is self-generated at ingest, stored in app's chroma directory
        with open(path, "rb") as f:
            data = pickle.load(f)
        idx = cls.__new__(cls)
        idx.ids = data["ids"]
        idx._bm25 = data["bm25"]
        idx.hash = data["hash"]
        return idx
