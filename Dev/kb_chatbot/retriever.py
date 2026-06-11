"""Embed query, vector-search ChromaDB, rerank, confidence-gate."""
from __future__ import annotations
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import chromadb
from sentence_transformers import SentenceTransformer, CrossEncoder

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.ingest import COLLECTION_NAME, open_persistent_client

log = logging.getLogger("kb_chatbot.retriever")


def _sigmoid(x: float) -> float:
    """Map a CrossEncoder logit to a 0-1 probability for a stable abstain floor."""
    if x < 0:
        z = math.exp(x)
        return z / (1.0 + z)
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class Filters:
    product: Optional[str] = None
    version_min: Optional[str] = None
    version_max: Optional[str] = None


@dataclass
class RetrievalResult:
    chunks: list[Chunk] = field(default_factory=list)
    raw_top_score: float = 0.0
    rerank_top_score: float = 0.0
    abstain_reason: Optional[str] = None


class Retriever:
    def __init__(
        self,
        chroma_path: Path,
        *,
        top_k_retrieve: int = config.TOP_K_RETRIEVE,
        top_k_rerank: int = config.TOP_K_RERANK,
        confidence_floor: float = config.CONFIDENCE_FLOOR,
        embedder: Optional[SentenceTransformer] = None,
    ):
        self.client = open_persistent_client(chroma_path)
        self.collection = self.client.get_or_create_collection(name=COLLECTION_NAME)
        self.embedder = embedder if embedder is not None else SentenceTransformer(config.EMBED_MODEL)
        self._reranker: Optional[CrossEncoder] = None  # loaded lazily on first rerank
        self.top_k_retrieve = top_k_retrieve
        self.top_k_rerank = top_k_rerank
        self.confidence_floor = confidence_floor

    def _get_reranker(self) -> CrossEncoder:
        if self._reranker is None:
            log.info("Loading reranker model (first use)...")
            self._reranker = CrossEncoder(config.RERANKER_MODEL)
        return self._reranker

    def _embed(self, text: str) -> list[float]:
        return self.embedder.encode(text, convert_to_numpy=True).tolist()

    def _query_chroma(self, query_vec: list[float], filters: Filters, n_results: int) -> list[Chunk]:
        where: dict = {}
        if filters.product:
            where["product"] = filters.product
        results = self.collection.query(
            query_embeddings=[query_vec],
            n_results=n_results,
            where=where or None,
        )
        chunks: list[Chunk] = []
        ids = results.get("ids", [[]])[0]
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        for cid, doc, meta in zip(ids, docs, metas):
            chunks.append(Chunk(id=cid, text=doc, metadata=dict(meta or {})))
        return chunks

    def retrieve(self, query: str, filters: Filters) -> RetrievalResult:
        query_vec = self._embed(query)
        candidates = self._query_chroma(query_vec, filters, self.top_k_retrieve)
        if not candidates:
            return RetrievalResult(abstain_reason="no_relevant_kb_match")

        pairs = [(query, c.text) for c in candidates]
        scores = self._get_reranker().predict(pairs)
        scored = sorted(zip(candidates, scores), key=lambda t: t[1], reverse=True)
        top = scored[: self.top_k_rerank]
        raw_top = float(top[0][1]) if top else -99.0
        top_score = _sigmoid(raw_top)   # 0-1 probability

        if top_score < self.confidence_floor:
            log.info("Abstaining: top score %.3f (logit %.3f) < floor %.3f",
                     top_score, raw_top, self.confidence_floor)
            return RetrievalResult(
                chunks=[], raw_top_score=raw_top,
                rerank_top_score=top_score, abstain_reason="no_relevant_kb_match",
            )

        return RetrievalResult(
            chunks=[c for c, _ in top], raw_top_score=raw_top, rerank_top_score=top_score,
        )

    def retrieve_quick(self, query: str, limit: int = 10) -> list[Chunk]:
        query_vec = self._embed(query)
        return self._query_chroma(query_vec, Filters(), limit)

    def suggest(self, query: str, top_k: int = 5) -> list[Chunk]:
        """Wide-net retrieval for article suggestions when confidence is low.
        Uses vector similarity only (no reranking, no confidence floor) to keep
        latency minimal. Returns up to top_k chunks deduplicated by title."""
        query_vec = self._embed(query)
        candidates = self._query_chroma(query_vec, Filters(), top_k * 2)
        seen_titles: set[str] = set()
        results: list[Chunk] = []
        for chunk in candidates:
            title = chunk.metadata.get("title", "")
            if title and title not in seen_titles:
                seen_titles.add(title)
                results.append(chunk)
            if len(results) >= top_k:
                break
        return results

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
        self.client = None
