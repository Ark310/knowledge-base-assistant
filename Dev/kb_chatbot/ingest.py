"""V2.7 ingest: incremental indexing of KB articles + support tickets into ChromaDB.

Every source file is tracked in index_manifest.json (path -> mtime, size, and the
chunk-ids it produced) so a reindex only re-embeds added/changed files and deletes
chunks for removed ones. Resolves the KB root and its sibling tickets/ folder
robustly so tickets are never silently missed, and emits structured progress
events for the GUI indexing panel."""
from __future__ import annotations
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import chromadb
from sentence_transformers import SentenceTransformer

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import build_article_chunks, Chunk
from Dev.kb_chatbot.ticket_ingest import build_ticket_chunks

log = logging.getLogger("kb_chatbot.ingest")

COLLECTION_NAME = "kbs"
BATCH_SIZE = 64
DELETE_BATCH = 256
MANIFEST_NAME = "index_manifest.json"
CHUNK_SCHEMA_VERSION = 3  # bump when ticket/article chunk text or metadata layout changes -> forces a clean re-embed

OnEvent = Callable[[dict], None]


class IngestCancelled(Exception):
    """Raised inside ingest() when should_cancel() returns True."""


class IngestSourceEmpty(Exception):
    """Raised when the configured source folder has no KB or ticket files. A
    reindex would otherwise wipe a populated index; instead we abort BEFORE any
    delete and leave the existing index untouched (e.g. the shipped exe has no
    library beside it — the user must point Settings at the real source folder)."""


@dataclass
class IngestReport:
    articles_seen: int = 0          # KB articles added/changed this run
    tickets_seen: int = 0           # tickets producing a chunk this run
    chunks_embedded: int = 0        # chunks newly embedded this run
    chunks_deleted: int = 0         # chunks removed this run (changed + removed files)
    total_chunks: int = 0           # total chunks in the collection after this run
    unchanged_files: int = 0        # source files skipped because mtime+size matched
    skipped: int = 0                # unreadable / no body_md / ticket with no resolution
    products: dict[str, int] = field(default_factory=dict)
    resolved_kb_path: str = ""
    resolved_tickets_path: str = ""
    duration_s: float = 0.0


def resolve_sources(library_path, tickets_path=None) -> tuple[Path, Path]:
    """Resolve (kb_root, tickets_root) regardless of whether library_path points
    at .../library or .../library/kb. An explicit tickets_path always wins."""
    library_path = Path(library_path)
    if library_path.name == "kb":
        kb_root = library_path
        tickets_root = library_path.parent / "tickets"
    elif (library_path / "kb").is_dir():
        kb_root = library_path / "kb"
        tickets_root = library_path / "tickets"
    else:
        kb_root = library_path
        tickets_root = library_path.parent / "tickets"
    if tickets_path is not None:
        tickets_root = Path(tickets_path)
    return kb_root, tickets_root


def open_persistent_client(chroma_path):
    """Open a chroma PersistentClient, retrying once on failure (the
    'table collections already exists' InternalError shows up when the sqlite is
    mid-sync under OneDrive or a prior client didn't close cleanly)."""
    chroma_path = Path(chroma_path)
    if "onedrive" in str(chroma_path).lower():
        log.warning("Chroma index lives under a OneDrive-synced path (%s); "
                    "cloud-sync of the live sqlite can corrupt it. A non-synced "
                    "location is recommended.", chroma_path)
    try:
        return chromadb.PersistentClient(path=str(chroma_path))
    except Exception as exc:
        log.warning("Chroma open failed (%s); retrying once", exc)
        import gc
        gc.collect()
        time.sleep(0.5)
        return chromadb.PersistentClient(path=str(chroma_path))


def _gather_article_jsons(kb_root: Path) -> list[Path]:
    if not kb_root.exists():
        return []
    out: list[Path] = []
    for child in sorted(kb_root.iterdir()):
        if child.is_dir():
            out.extend(sorted(child.rglob("*.json")))
    return [p for p in out if p.name != "index.json"]


def _gather_ticket_jsons(tickets_root: Path) -> list[Path]:
    if not tickets_root.exists():
        return []
    return [p for p in sorted(tickets_root.glob("ticket_*.json")) if p.name != "index.json"]


def _load_manifest(chroma_path: Path) -> dict:
    mf = chroma_path / MANIFEST_NAME
    if mf.exists():
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("files"), dict):
                return data
        except Exception:
            log.warning("Manifest unreadable; rebuilding from empty")
    return {"version": 1, "embed_model": "", "files": {}}


def _save_manifest(chroma_path: Path, manifest: dict) -> None:
    (chroma_path / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")


def _sig(p: Path) -> list:
    st = p.stat()
    return [st.st_mtime, st.st_size]


def _embed_batch(model, texts: list[str]) -> list[list[float]]:
    vecs = model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
    return [v.tolist() for v in vecs]


def ingest(
    library_path,
    chroma_path,
    *,
    tickets_path=None,
    on_event: Optional[OnEvent] = None,
    force_rebuild: bool = False,
    embedder=None,
    collection=None,
    should_cancel: Callable[[], bool] = lambda: False,
) -> IngestReport:
    """Incrementally index KB articles + tickets into ChromaDB.

    Pass `collection=` to reuse an already-open chroma collection (the GUI passes
    the live Retriever's collection so only one client touches the sqlite). Pass
    `embedder=` to reuse a loaded SentenceTransformer. `on_event` receives dicts
    {stage, message, current, total, counts}."""
    started = time.time()
    emit = on_event or (lambda e: None)
    chroma_path = Path(chroma_path)
    chroma_path.mkdir(parents=True, exist_ok=True)

    kb_root, tickets_root = resolve_sources(library_path, tickets_path)
    report = IngestReport(resolved_kb_path=str(kb_root),
                          resolved_tickets_path=str(tickets_root))

    own_client = collection is None
    client = None
    if own_client:
        client = open_persistent_client(chroma_path)
        collection = client.get_or_create_collection(name=COLLECTION_NAME)

    try:
        model = embedder if embedder is not None else SentenceTransformer(config.EMBED_MODEL)
        manifest = _load_manifest(chroma_path)

        # -- Scan FIRST --------------------------------------------------------
        # Scan the source BEFORE clearing anything. A reindex must never destroy a
        # populated index when the configured source folder is missing or empty
        # (e.g. the shipped exe with no library beside it). So the empty-source
        # guard runs ahead of the force-rebuild / embed-model-change delete below.
        emit({"stage": "scan", "message": "Scanning sources...",
              "current": None, "total": None, "counts": {}})
        kb_files = _gather_article_jsons(kb_root)
        ticket_files = _gather_ticket_jsons(tickets_root)
        emit({"stage": "scan",
              "message": f"KB root {kb_root}: {len(kb_files)} files | "
                         f"Tickets {tickets_root}: {len(ticket_files)} files",
              "current": None, "total": None,
              "counts": {"kb_files": len(kb_files), "ticket_files": len(ticket_files)}})
        if not kb_files and not ticket_files:
            msg = (f"No source files found. KB root: {kb_root} | Tickets: {tickets_root}. "
                   f"Index left unchanged — set the knowledge-base source folder in Settings.")
            emit({"stage": "error", "message": msg,
                  "current": None, "total": None, "counts": {}})
            raise IngestSourceEmpty(msg)
        if not ticket_files:
            emit({"stage": "scan",
                  "message": f"WARNING: 0 ticket files found at {tickets_root}",
                  "current": None, "total": None, "counts": {}})

        # -- Now safe to clear for a full rebuild / embed-model / schema change -
        model_changed = manifest.get("embed_model") not in ("", config.EMBED_MODEL)
        schema_changed = bool(manifest.get("files")) and \
            manifest.get("chunk_schema_version") != CHUNK_SCHEMA_VERSION
        if force_rebuild or model_changed or schema_changed:
            ids = collection.get(include=[]).get("ids", [])
            for i in range(0, len(ids), DELETE_BATCH):
                collection.delete(ids=ids[i:i + DELETE_BATCH])
            manifest = {"version": 1, "embed_model": config.EMBED_MODEL,
                        "chunk_schema_version": CHUNK_SCHEMA_VERSION, "files": {}}
        manifest["embed_model"] = config.EMBED_MODEL
        manifest["chunk_schema_version"] = CHUNK_SCHEMA_VERSION
        files = manifest["files"]

        current: dict[str, tuple] = {}
        for f in kb_files:
            current["kb/" + f.relative_to(kb_root).as_posix()] = ("kb", f, _sig(f))
        for tf in ticket_files:
            current["ticket/" + tf.name] = ("ticket", tf, _sig(tf))

        # -- Diff --------------------------------------------------------------
        added, changed, removed, unchanged = [], [], [], []
        for key, (_kind, _path, sig) in current.items():
            prev = files.get(key)
            if prev is None:
                added.append(key)
            elif [prev.get("mtime"), prev.get("size")] != sig:
                changed.append(key)
            else:
                unchanged.append(key)
        for key in list(files):
            if key not in current:
                removed.append(key)
        report.unchanged_files = len(unchanged)
        emit({"stage": "diff",
              "message": f"{len(added)} new | {len(changed)} changed | "
                         f"{len(removed)} removed | {len(unchanged)} unchanged",
              "current": None, "total": None,
              "counts": {"new": len(added), "changed": len(changed),
                         "removed": len(removed), "unchanged": len(unchanged)}})

        # -- Delete chunks for removed + changed files -------------------------
        delete_ids: list[str] = []
        for key in removed + changed:
            delete_ids.extend(files.get(key, {}).get("chunk_ids", []))
        for i in range(0, len(delete_ids), DELETE_BATCH):
            collection.delete(ids=delete_ids[i:i + DELETE_BATCH])
        report.chunks_deleted = len(delete_ids)
        for key in removed:
            files.pop(key, None)

        # -- Build chunks for added + changed files ----------------------------
        to_process = added + changed
        kb_keys = [k for k in to_process if current[k][0] == "kb"]
        ticket_keys = [k for k in to_process if current[k][0] == "ticket"]
        pending: list[Chunk] = []
        file_chunk_ids: dict[str, list[str]] = {}

        total_kb = len(kb_keys)
        for i, key in enumerate(kb_keys, 1):
            if should_cancel():
                raise IngestCancelled()
            _kind, f, _sigv = current[key]
            file_chunk_ids[key] = []
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
            chunks = build_article_chunks(data, f, kb_root)
            file_chunk_ids[key] = [c.id for c in chunks]
            pending.extend(chunks)
            if i % 50 == 0 or i == total_kb:
                emit({"stage": "parse_kb", "message": f"Parsed {i}/{total_kb} KB articles",
                      "current": i, "total": total_kb,
                      "counts": {"kb_articles": report.articles_seen, "chunks": len(pending)}})

        total_tk = len(ticket_keys)
        for i, key in enumerate(ticket_keys, 1):
            if should_cancel():
                raise IngestCancelled()
            _kind, tf, _sigv = current[key]
            file_chunk_ids[key] = []
            try:
                tdata = json.loads(tf.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("Skipping unreadable ticket %s: %s", tf, exc)
                report.skipped += 1
                continue
            tchunks = build_ticket_chunks(tdata, tf)
            if tchunks:
                report.tickets_seen += 1
                file_chunk_ids[key] = [c.id for c in tchunks]
                pending.extend(tchunks)
            else:
                report.skipped += 1
            if i % 200 == 0 or i == total_tk:
                emit({"stage": "redact_tickets",
                      "message": f"Redacted + parsed {i}/{total_tk} tickets",
                      "current": i, "total": total_tk,
                      "counts": {"tickets": report.tickets_seen, "chunks": len(pending)}})

        # -- Embed + upsert ----------------------------------------------------
        total = len(pending)
        embedded = 0
        for i in range(0, total, BATCH_SIZE):
            if should_cancel():
                raise IngestCancelled()
            batch = pending[i:i + BATCH_SIZE]
            embeds = _embed_batch(model, [c.text for c in batch])
            collection.upsert(
                ids=[c.id for c in batch],
                documents=[c.text for c in batch],
                embeddings=embeds,
                metadatas=[c.metadata for c in batch],
            )
            embedded += len(batch)
            emit({"stage": "embed", "message": f"Embedded {embedded}/{total} chunks",
                  "current": embedded, "total": total,
                  "counts": {"chunks_embedded": embedded}})
        report.chunks_embedded = embedded

        # -- Persist manifest --------------------------------------------------
        for key in to_process:
            _kind, _path, sig = current[key]
            files[key] = {"mtime": sig[0], "size": sig[1],
                          "chunk_ids": file_chunk_ids.get(key, [])}
        manifest["files"] = files
        emit({"stage": "persist", "message": "Saving index manifest...",
              "current": None, "total": None, "counts": {}})
        _save_manifest(chroma_path, manifest)

        report.total_chunks = collection.count()
        report.duration_s = time.time() - started
        emit({"stage": "done",
              "message": (f"Done: +{report.chunks_embedded} embedded, "
                          f"-{report.chunks_deleted} removed, "
                          f"{report.total_chunks} total, {report.duration_s:.1f}s"),
              "current": total or 1, "total": total or 1,
              "counts": {"total_chunks": report.total_chunks,
                         "tickets": report.tickets_seen,
                         "kb_articles": report.articles_seen}})
        log.info("Ingest: +%d embedded, -%d removed, %d total, %.1fs (kb=%s tickets=%s)",
                 report.chunks_embedded, report.chunks_deleted, report.total_chunks,
                 report.duration_s, kb_root, tickets_root)
        return report
    finally:
        if own_client and client is not None:
            client.close()
