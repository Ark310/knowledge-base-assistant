import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters
from Dev.kb_chatbot.llm.fake_provider import FakeProvider
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chat.answer_cache import AnswerCache
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


@pytest.fixture(scope="module")
def tmp_index():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))
    return tmp


def test_repeat_standalone_question_served_from_cache(tmp_index, tmp_path):
    r = Retriever(Path(tmp_index), confidence_floor=0.0)
    r.suggest = lambda query, top_k=5: []
    cache = AnswerCache(tmp_path / "cache.json")
    llm = FakeProvider(canned_text="Answer [TradeDesk · dealing · Booking a Spot Deal].")
    deps = Deps(retriever=r, llm=llm, answer_cache=cache)

    t1 = handle_turn("How do I book a spot deal in TradeDesk?", Session.new(),
                     Filters(product="tradedesk"), "claude-haiku-4-5-20251001", deps=deps)
    assert t1.kind == "answer"
    assert len(llm.calls) == 1

    # Identical question in a FRESH session -> served from cache, no second LLM call.
    t2 = handle_turn("How do I book a spot deal in TradeDesk?", Session.new(),
                     Filters(product="tradedesk"), "claude-haiku-4-5-20251001", deps=deps)
    assert t2.kind == "answer"
    assert t2.content == t1.content
    assert len(llm.calls) == 1   # unchanged -> cache hit


def test_classifier_delegation_preserves_error_detection():
    from Dev.kb_chatbot.chat.orchestrator import _looks_like_error, _extract_ticket_ids, _extract_single_product
    assert _looks_like_error("GetWebDeal returns a null buy amount error")
    assert not _looks_like_error("how do I book a spot deal")
    assert _extract_ticket_ids("ticket 75919") == ["75919"]
    assert _extract_single_product("how do I use tradedesk") == "tradedesk"
