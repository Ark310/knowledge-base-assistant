"""Embed query, vector-search ChromaDB, rerank, confidence-gate."""
from __future__ import annotations
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from sentence_transformers import SentenceTransformer, CrossEncoder

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.ingest import COLLECTION_NAME, open_persistent_client
from Dev.kb_chatbot.chat.query_norm import tokenize

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


def _strip_title_line(text: str) -> str:
    """Drop the leading 'Ticket #<id> — <title>' line (and the blank line after it)
    from a non-first chunk, leaving just its body segment."""
    parts = text.split("\n\n", 1)
    return parts[1].strip() if len(parts) == 2 else text.strip()


def assemble_ticket(chunks: list[Chunk]) -> Chunk:
    """Reassemble the full ticket from its sibling chunks (parent-document
    retrieval). Orders by chunk_index; chunk 0 (with the staff/client header)
    leads, subsequent chunks contribute their body segment only. Returns one
    Chunk carrying chunk 0's metadata (chunk_index normalised to 0)."""
    ordered = sorted(chunks, key=lambda c: int(c.metadata.get("chunk_index", 0)))
    head = ordered[0]
    text = head.text.strip()
    for c in ordered[1:]:
        seg = _strip_title_line(c.text)
        if seg:
            text += "\n\n" + seg
    meta = dict(head.metadata)
    meta["chunk_index"] = 0
    return Chunk(id=head.id, text=text, metadata=meta)


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
        self._bm25 = None                 # lazy BM25Okapi, built from the collection
        self._bm25_ids: list[str] = []
        self._bm25_docs: list[str] = []
        self._bm25_meta: list[dict] = []

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

    # ── Hybrid (BM25 keyword) retrieval ──────────────────────────────────────
    def _ensure_bm25(self) -> None:
        if self._bm25 is not None or self._bm25_ids:
            return
        got = self.collection.get(include=["documents", "metadatas"])
        self._bm25_ids = got.get("ids", []) or []
        self._bm25_docs = [d or "" for d in (got.get("documents", []) or [])]
        self._bm25_meta = [dict(m or {}) for m in (got.get("metadatas", []) or [])]
        if self._bm25_ids:
            from rank_bm25 import BM25Okapi
            self._bm25 = BM25Okapi([tokenize(d) for d in self._bm25_docs])

    def invalidate_bm25(self) -> None:
        """Drop the cached BM25 index so the next retrieve rebuilds it (call after a reindex)."""
        self._bm25 = None
        self._bm25_ids = []
        self._bm25_docs = []
        self._bm25_meta = []

    def _bm25_candidates(self, query: str, filters: Filters, n: int) -> list[Chunk]:
        self._ensure_bm25()
        if self._bm25 is None:
            return []
        scores = self._bm25.get_scores(tokenize(query))
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], self._bm25_ids[i]))
        out: list[Chunk] = []
        for i in order:
            if scores[i] <= 0:
                break
            if filters.product and self._bm25_meta[i].get("product") != filters.product:
                continue
            out.append(Chunk(id=self._bm25_ids[i], text=self._bm25_docs[i],
                             metadata=dict(self._bm25_meta[i])))
            if len(out) >= n:
                break
        return out

    def _rrf_fuse(self, vec_list: list[Chunk], bm25_list: list[Chunk], k: int) -> list[Chunk]:
        ranked: dict[str, list] = {}   # id -> [chunk, score]
        for rank, c in enumerate(vec_list):
            ranked.setdefault(c.id, [c, 0.0])[1] += 1.0 / (k + rank + 1)
        for rank, c in enumerate(bm25_list):
            entry = ranked.setdefault(c.id, [c, 0.0])
            entry[1] += 1.0 / (k + rank + 1)
        fused = sorted(ranked.values(), key=lambda t: (-t[1], t[0].id))
        return [c for c, _ in fused]

    def _chunks_from_get(self, got: dict) -> list[Chunk]:
        """Build Chunks from a collection.get() result (flat lists, not nested)."""
        ids = got.get("ids", []) or []
        docs = got.get("documents", []) or []
        metas = got.get("metadatas", []) or []
        return [Chunk(id=cid, text=doc or "", metadata=dict(meta or {}))
                for cid, doc, meta in zip(ids, docs, metas)]

    def get_by_ids(self, ids: list[str]) -> list[Chunk]:
        """Fetch chunks by their chunk-id (used to carry a prior turn's context)."""
        if not ids:
            return []
        return self._chunks_from_get(self.collection.get(ids=list(ids)))

    def get_by_ticket_ids(self, ticket_ids: list[str]) -> list[Chunk]:
        """Fetch ticket chunks by ticket_id metadata (explicit 'ticket #N' lookup)."""
        wanted = [str(t) for t in ticket_ids if str(t)]
        if not wanted:
            return []
        where = {"ticket_id": wanted[0]} if len(wanted) == 1 else {"ticket_id": {"$in": wanted}}
        return self._chunks_from_get(self.collection.get(where=where))

    def retrieve(self, query: str, filters: Filters, top_k_rerank: Optional[int] = None) -> RetrievalResult:
        query_vec = self._embed(query)
        vec_c = self._query_chroma(query_vec, filters, self.top_k_retrieve)
        if config.HYBRID_ENABLED:
            bm_c = self._bm25_candidates(query, filters, config.BM25_TOP_K)
            candidates = self._rrf_fuse(vec_c, bm_c, config.RRF_K)
        else:
            candidates = vec_c
        if not candidates:
            return RetrievalResult(abstain_reason="no_relevant_kb_match")

        pairs = [(query, c.text) for c in candidates]
        scores = self._get_reranker().predict(pairs)
        scored = sorted(zip(candidates, scores), key=lambda t: (-float(t[1]), t[0].id))
        k = top_k_rerank or self.top_k_rerank
        top = scored[:k]
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
