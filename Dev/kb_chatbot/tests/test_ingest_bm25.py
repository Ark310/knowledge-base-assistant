import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config
from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.lexical import LexicalIndex

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


def test_ingest_writes_loadable_bm25_index():
    with tempfile.TemporaryDirectory() as tmp:
        report = ingest(FIX, Path(tmp))
        pkl = Path(tmp) / config.BM25_FILE
        assert pkl.exists()
        idx = LexicalIndex.load(pkl)
        assert len(idx.ids) == report.chunks_created
        # an exact keyword present in the fixture corpus is findable
        assert idx.query("spot deal booking", top_n=5)


def test_reingest_keeps_index_consistent_with_collection():
    import chromadb
    from Dev.kb_chatbot.ingest import COLLECTION_NAME
    from Dev.kb_chatbot.lexical import corpus_hash
    with tempfile.TemporaryDirectory() as tmp:
        ingest(FIX, Path(tmp))
        ingest(FIX, Path(tmp))  # upsert same content again
        client = chromadb.PersistentClient(path=tmp)
        ids = client.get_collection(COLLECTION_NAME).get(include=[])["ids"]
        client.close()
        idx = LexicalIndex.load(Path(tmp) / config.BM25_FILE)
        assert idx.hash == corpus_hash(ids)
