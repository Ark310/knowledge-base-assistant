import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.lexical import LexicalIndex, tokenize, corpus_hash

ITEMS = [
    ("id1", "Booking a spot deal in the dealing tab"),
    ("id2", "Recurring payment sweep failed with ERR-7741"),
    ("id3", "How to build a form in SalesHub form management"),
]


def test_tokenize_lowercases_and_splits_alphanumerics():
    assert tokenize("Sweep failed: ERR-7741!") == ["sweep", "failed", "err", "7741"]


def test_exact_keyword_match_ranks_first():
    idx = LexicalIndex.build(ITEMS)
    assert idx.query("ERR-7741 sweep", top_n=3)[0] == "id2"


def test_query_with_no_overlap_returns_empty():
    idx = LexicalIndex.build(ITEMS)
    assert idx.query("zzz qqq xxx", top_n=3) == []


def test_save_load_roundtrip(tmp_path):
    idx = LexicalIndex.build(ITEMS)
    p = tmp_path / "bm25.pkl"
    idx.save(p)
    loaded = LexicalIndex.load(p)
    assert loaded.ids == idx.ids
    assert loaded.hash == idx.hash
    assert loaded.query("spot deal", top_n=1) == ["id1"]


def test_corpus_hash_is_order_independent_and_content_sensitive():
    assert corpus_hash(["a", "b"]) == corpus_hash(["b", "a"])
    assert corpus_hash(["a", "b"]) != corpus_hash(["a", "c"])


def test_build_empty_corpus_is_safe():
    idx = LexicalIndex.build([])
    assert idx.query("anything", top_n=5) == []


def test_common_term_with_nonpositive_idf_still_matches():
    # 'spot' appears in 1 of 2 docs -> IDF = 0 in BM25Okapi; presence filter
    # must still return the containing doc (zero-score filter regression).
    idx = LexicalIndex.build([
        ("d1", "spot deal booking"),
        ("d2", "form management basics"),
    ])
    assert idx.query("spot", top_n=2) == ["d1"]
