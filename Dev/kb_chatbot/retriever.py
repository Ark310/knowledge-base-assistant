"""Embed query, vector-search ChromaDB, rerank, confidence-gate."""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import chromadb
from sentence_transformers import SentenceTransformer, CrossEncoder

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.ingest import COLLECTION_NAME
from Dev.kb_chatbot.expansion import expand_query, load_synonyms
from Dev.kb_chatbot.fusion import rrf_fuse
from Dev.kb_chatbot.lexical import LexicalIndex, corpus_hash

log = logging.getLogger("kb_chatbot.retriever")


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
