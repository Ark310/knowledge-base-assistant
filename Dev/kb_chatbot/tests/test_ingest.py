import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.ingest import ingest
import json
from Dev.kb_chatbot.ingest import resolve_sources, IngestReport

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


def test_ingest_reports_article_count():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert report.articles_seen == 6


def test_ingest_creates_chunks():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert report.chunks_embedded >= 6
        assert report.total_chunks >= 6


def test_ingest_per_product_counts():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert set(report.products.keys()) == {"api", "tradedesk", "saleshub", "web2", "web4", "other"}
        assert all(v == 1 for v in report.products.values())


def test_ingest_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        r1 = ingest(FIX, Path(tmp))
        r2 = ingest(FIX, Path(tmp))
        assert r1.total_chunks == r2.total_chunks
        assert r2.chunks_embedded == 0
        assert r2.unchanged_files == 6


def test_ingest_collection_queryable_after_ingest():
    import chromadb
    with tempfile.TemporaryDirectory() as tmp:
        ingest(FIX, Path(tmp))
        client = chromadb.PersistentClient(path=str(tmp))
        coll = client.get_collection("kbs")
        all_records = coll.get()
        assert len(all_records["ids"]) >= 6
        products = {m["product"] for m in all_records["metadatas"]}
        assert products == {"api", "tradedesk", "saleshub", "web2", "web4", "other"}
        client.close()


def _write_article(dirpath, name, title, body="hello world"):
    dirpath.mkdir(parents=True, exist_ok=True)
    (dirpath / name).write_text(
        json.dumps({"product": "api", "title": title, "body_md": body}),
        encoding="utf-8")


def test_resolve_sources_kb_leaf(tmp_path):
    (tmp_path / "kb").mkdir()
    (tmp_path / "tickets").mkdir()
    kb, tk = resolve_sources(tmp_path / "kb")
    assert kb == tmp_path / "kb"
    assert tk == tmp_path / "tickets"


def test_resolve_sources_library_parent(tmp_path):
    (tmp_path / "kb").mkdir()
    (tmp_path / "tickets").mkdir()
    kb, tk = resolve_sources(tmp_path)
    assert kb == tmp_path / "kb"
    assert tk == tmp_path / "tickets"


def test_resolve_sources_explicit_tickets_wins(tmp_path):
    kb, tk = resolve_sources(tmp_path / "kb", tickets_path=tmp_path / "custom")
    assert tk == tmp_path / "custom"


def test_incremental_skips_unchanged(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    assert r1.articles_seen == 1 and r1.chunks_embedded >= 1
    r2 = ingest(lib, chroma)
    assert r2.chunks_embedded == 0
    assert r2.unchanged_files == 1
    assert r2.total_chunks == r1.total_chunks


def test_incremental_processes_added_file(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    _write_article(lib / "api", "b.json", "B", body="more content here")
    r3 = ingest(lib, chroma)
    assert r3.articles_seen == 1
    assert r3.chunks_embedded >= 1
    assert r3.total_chunks == r1.total_chunks + r3.chunks_embedded


def test_incremental_deletes_removed_file_chunks(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    _write_article(lib / "api", "b.json", "B", body="second article body")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    (lib / "api" / "b.json").unlink()
    r2 = ingest(lib, chroma)
    assert r2.chunks_deleted >= 1
    assert r2.total_chunks < r1.total_chunks


def test_force_rebuild_reembeds_everything(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    r2 = ingest(lib, chroma, force_rebuild=True)
    assert r2.chunks_embedded == r1.chunks_embedded
    assert r2.total_chunks == r1.total_chunks


def test_embed_model_change_forces_rebuild(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    mf = chroma / "index_manifest.json"
    data = json.loads(mf.read_text(encoding="utf-8"))
    data["embed_model"] = "some-other-model"
    mf.write_text(json.dumps(data), encoding="utf-8")
    r2 = ingest(lib, chroma)
    assert r2.chunks_embedded == r1.chunks_embedded


def test_tickets_indexed_via_explicit_path(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    tickets = tmp_path / "tickets"
    tickets.mkdir()
    (tickets / "ticket_40000.json").write_text(json.dumps({
        "ticket_id": "40000",
        "title": "Login fails",
        "product": "tradedesk",
        "resolution_url": "https://support.example/40000",
        "comments": [
            {"type": "note", "body": "Customer cannot log in."},
            {"type": "comment", "author": "Staff",
             "body": "Cleared the cache and restarted the service; resolved."},
        ],
    }), encoding="utf-8")
    chroma = tmp_path / "chroma"
    report = ingest(lib, chroma, tickets_path=tickets)
    assert report.tickets_seen == 1
    assert report.resolved_tickets_path == str(tickets)
    import chromadb
    client = chromadb.PersistentClient(path=str(chroma))
    coll = client.get_collection("kbs")
    kinds = {m.get("kind") for m in coll.get()["metadatas"]}
    assert "ticket" in kinds
    client.close()


def test_reindex_refuses_empty_source_and_keeps_index(tmp_path):
    # A reindex pointed at a missing/empty source must NOT wipe a populated index
    # (the exe-with-no-library data-loss bug). It must abort BEFORE any delete.
    from Dev.kb_chatbot.ingest import IngestSourceEmpty
    import chromadb
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    assert r1.total_chunks >= 1

    empty = tmp_path / "empty_root"
    empty.mkdir()
    try:
        ingest(empty, chroma, force_rebuild=True)  # force-rebuild + empty source
        assert False, "expected IngestSourceEmpty"
    except IngestSourceEmpty:
        pass

    client = chromadb.PersistentClient(path=str(chroma))
    assert client.get_collection("kbs").count() == r1.total_chunks  # index untouched
    client.close()


def test_event_stages_emitted(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    stages = []
    ingest(lib, chroma, on_event=lambda e: stages.append(e["stage"]))
    for s in ("scan", "diff", "embed", "persist", "done"):
        assert s in stages


def test_cancel_then_reindex_recovers_changed_file(tmp_path):
    from Dev.kb_chatbot.ingest import IngestCancelled
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A", body="original body text here")
    chroma = tmp_path / "chroma"
    ingest(lib, chroma)
    # modify the file, then cancel the reindex immediately
    _write_article(lib / "api", "a.json", "A", body="completely new body text now")
    try:
        ingest(lib, chroma, should_cancel=lambda: True)
        assert False, "expected IngestCancelled"
    except IngestCancelled:
        pass
    # a normal reindex afterwards must re-embed the changed file (self-heal, no permanent loss)
    r = ingest(lib, chroma)
    assert r.chunks_embedded >= 1
    assert r.total_chunks >= 1


def test_chunk_schema_change_forces_rebuild(tmp_path):
    lib = tmp_path / "kb"
    _write_article(lib / "api", "a.json", "A")
    chroma = tmp_path / "chroma"
    r1 = ingest(lib, chroma)
    mf = chroma / "index_manifest.json"
    data = json.loads(mf.read_text(encoding="utf-8"))
    assert data.get("chunk_schema_version") is not None  # written on ingest
    data["chunk_schema_version"] = 0                      # simulate an older schema
    mf.write_text(json.dumps(data), encoding="utf-8")
    r2 = ingest(lib, chroma)
    assert r2.chunks_embedded == r1.chunks_embedded       # all re-embedded
