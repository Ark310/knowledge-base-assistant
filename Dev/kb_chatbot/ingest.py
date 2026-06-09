"""V2.2 ingest: walks <library>/<product>/**/*.json, skips index files and files without body_md.
Builds article chunks and persists them in ChromaDB."""
from __future__ import annotations
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import chromadb
from sentence_transformers import SentenceTransformer

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import build_article_chunks, Chunk
from Dev.kb_chatbot.lexical import LexicalIndex

log = logging.getLogger("kb_chatbot.ingest")

COLLECTION_NAME = "kbs"
BATCH_SIZE = 64


@dataclass
class IngestReport:
    articles_seen: int = 0
    chunks_created: int = 0
    products: dict[str, int] = field(default_factory=dict)
    skipped: int = 0
    duration_s: float = 0.0


def _gather_article_jsons(library_path: Path) -> list[Path]:
    """All .json files under product directories, skipping index.json at the root."""
    if not library_path.exists():
        return []
    out: list[Path] = []
    for child in sorted(library_path.iterdir()):
        if child.is_dir():
            out.extend(sorted(child.rglob("*.json")))
    return [p for p in out if p.name != "index.json"]


def _embed_batch(model: SentenceTransformer, texts: list[str]) -> list[list[float]]:
    vecs = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]


def ingest(
    library_path: Path,
    chroma_path: Path,
    on_progress: Callable[[int, int], None] = lambda done, total: None,
    overlap_words: int = config.CHUNK_OVERLAP_WORDS,
) -> IngestReport:
    started = time.time()
    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    collection = client.get_or_create_collection(name=COLLECTION_NAME)
    embedder = SentenceTransformer(config.EMBED_MODEL)

    files = _gather_article_jsons(library_path)
    report = IngestReport()
    all_chunks: list[Chunk] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Skipping unreadable %s: %s", f, exc)
            report.skipped += 1
            continue
        if not isinstance(data, dict) or not data.get("body_md"):
            report.skipped += 1
            continue
        product = data.get("product", "unknown")
        report.articles_seen += 1
        report.products[product] = report.products.get(product, 0) + 1
        all_chunks.extend(build_article_chunks(data, f, library_path, overlap_words=overlap_words))

    total = len(all_chunks)
    if total == 0:
        client.close()
        report.duration_s = time.time() - started
        return report

    for i in range(0, total, BATCH_SIZE):
        batch = all_chunks[i : i + BATCH_SIZE]
        embeds = _embed_batch(embedder, [c.text for c in batch])
        collection.upsert(
            ids=[c.id for c in batch],
            documents=[c.text for c in batch],
            embeddings=embeds,
            metadatas=[c.metadata for c in batch],
        )
        on_progress(min(i + len(batch), total), total)

    # Build the BM25 sidecar from the COLLECTION (not just this batch) so the
    # lexical index always mirrors chroma exactly, even after partial re-ingests.
    stored = collection.get(include=["documents"])
    lexical = LexicalIndex.build(list(zip(stored["ids"], stored["documents"])))
    lexical.save(chroma_path / config.BM25_FILE)
    log.info("BM25 index: %d docs → %s", len(stored["ids"]), config.BM25_FILE)

    report.chunks_created = total
    report.duration_s = time.time() - started
    log.info("Ingest: %d articles, %d chunks, %.1fs",
             report.articles_seen, report.chunks_created, report.duration_s)
    client.close()
    return report
