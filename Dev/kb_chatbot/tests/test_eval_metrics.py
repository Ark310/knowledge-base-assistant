import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.eval.metrics import unique_article_urls, recall_at_k, mrr
from Dev.kb_chatbot.chunker import Chunk


def _chunk(url):
    return Chunk(id=url, text="t", metadata={"url": url})


def test_unique_article_urls_preserves_rank_order():
    chunks = [_chunk("u1"), _chunk("u2"), _chunk("u1"), _chunk("u3")]
    assert unique_article_urls(chunks) == ["u1", "u2", "u3"]


def test_recall_at_k_hit_and_miss():
    assert recall_at_k(["a", "b", "c"], expected=["b"], k=3) is True
    assert recall_at_k(["a", "b", "c"], expected=["z"], k=3) is False
    assert recall_at_k(["a", "b", "c"], expected=["c"], k=2) is False  # outside k


def test_recall_any_expected_counts():
    assert recall_at_k(["a"], expected=["z", "a"], k=1) is True


def test_mrr_reciprocal_rank_of_first_hit():
    assert mrr(["x", "a", "b"], expected=["a"]) == 0.5
    assert mrr(["a"], expected=["a"]) == 1.0
    assert mrr(["x", "y"], expected=["a"]) == 0.0
