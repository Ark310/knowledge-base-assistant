import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat.answer_cache import AnswerCache, make_key


def test_make_key_varies_by_product_and_model():
    k1 = make_key("how do i book a deal", "tradedesk", "claude-sonnet-4-6")
    k2 = make_key("how do i book a deal", "web4", "claude-sonnet-4-6")
    k3 = make_key("how do i book a deal", "tradedesk", "gpt-5.4")
    assert k1 != k2 and k2 != k3 and k1 != k3

def test_put_then_get_roundtrips(tmp_path):
    c = AnswerCache(tmp_path / "cache.json")
    c.put("k1", {"content": "answer", "model": "m"})
    assert c.get("k1") == {"content": "answer", "model": "m"}

def test_miss_returns_none(tmp_path):
    c = AnswerCache(tmp_path / "cache.json")
    assert c.get("nope") is None

def test_persists_across_instances(tmp_path):
    p = tmp_path / "cache.json"
    AnswerCache(p).put("k", {"content": "x"})
    assert AnswerCache(p).get("k") == {"content": "x"}

def test_evicts_oldest_beyond_max(tmp_path):
    c = AnswerCache(tmp_path / "cache.json", max_entries=2)
    c.put("a", {"content": "1"}); c.put("b", {"content": "2"}); c.put("c", {"content": "3"})
    assert c.get("a") is None          # oldest evicted
    assert c.get("b") is not None and c.get("c") is not None
