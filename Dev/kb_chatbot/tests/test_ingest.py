import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.ingest import ingest

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


def test_ingest_reports_article_count():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert report.articles_seen == 6


def test_ingest_creates_chunks():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert report.chunks_created >= 6


def test_ingest_per_product_counts():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        assert set(report.products.keys()) == {"api", "tradedesk", "saleshub", "web2", "web4", "other"}
        assert all(v == 1 for v in report.products.values())


def test_ingest_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        r1 = ingest(FIX, Path(tmp))
        r2 = ingest(FIX, Path(tmp))
        assert r1.chunks_created == r2.chunks_created


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
