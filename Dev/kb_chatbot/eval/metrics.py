"""Pure scoring functions for the retrieval eval harness."""
from __future__ import annotations

from Dev.kb_chatbot.chunker import Chunk


def unique_article_urls(chunks: list[Chunk]) -> list[str]:
    """Article-level ranking: unique chunk URLs in retrieval order."""
    seen: set[str] = set()
    out: list[str] = []
    for c in chunks:
        url = c.metadata.get("url", "")
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def recall_at_k(retrieved_urls: list[str], expected: list[str], k: int) -> bool:
    return any(url in expected for url in retrieved_urls[:k])


def mrr(retrieved_urls: list[str], expected: list[str]) -> float:
    for i, url in enumerate(retrieved_urls):
        if url in expected:
            return 1.0 / (i + 1)
    return 0.0
