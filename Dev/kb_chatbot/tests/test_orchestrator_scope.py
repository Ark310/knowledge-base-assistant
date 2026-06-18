import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps, OUT_OF_SCOPE_MESSAGE
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.retriever import Filters, RetrievalResult
from Dev.kb_chatbot.llm.fake_provider import FakeProvider


def _kb(title, url):
    return Chunk(id="k", text="content",
                 metadata={"product": "tradedesk", "category": "dealing",
                           "title": title, "url": url})


class ScopeRetriever:
    """abstains with a configurable score; suggest returns one article."""
    def __init__(self, score):
        self.score = score
    def retrieve(self, query, filters):
        return RetrievalResult(chunks=[], abstain_reason="no_relevant_kb_match",
                               rerank_top_score=self.score)
    def get_by_ids(self, ids): return []
    def get_by_ticket_ids(self, tids): return []
    def retrieve_quick(self, query, limit=10): return []
    def suggest(self, query, top_k=5):
        return [_kb("Booking a Spot Deal", "https://help.contoso.example/spot")]


def test_clearly_unrelated_returns_out_of_scope_no_suggestions():
    d = Deps(retriever=ScopeRetriever(config.OUT_OF_SCOPE_FLOOR - 0.005),
             llm=FakeProvider(canned_text="should not be seen"))
    turn = handle_turn("what is the boiling point of helium today",
                       Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "abstain"
    assert turn.content == OUT_OF_SCOPE_MESSAGE
    assert "help.contoso.example/spot" not in turn.content  # no suggestions for out-of-scope


def test_related_but_weak_still_suggests():
    # score between OUT_OF_SCOPE_FLOOR and CONFIDENCE_FLOOR -> suggestions path (not scope msg)
    score = (config.OUT_OF_SCOPE_FLOOR + config.CONFIDENCE_FLOOR) / 2
    d = Deps(retriever=ScopeRetriever(score),
             llm=FakeProvider(canned_text="should not be seen"))
    turn = handle_turn("how do I configure dealing spreads maybe",
                       Session.new(), Filters(product="tradedesk"),
                       "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "abstain"
    assert turn.content != OUT_OF_SCOPE_MESSAGE
    assert "help.contoso.example/spot" in turn.content  # suggestions present


def test_out_of_scope_skips_rewrite_escalation():
    calls = {"n": 0}
    def rewriter(user_msg, history):
        calls["n"] += 1
        return None
    d = Deps(retriever=ScopeRetriever(config.OUT_OF_SCOPE_FLOOR - 0.005),
             llm=FakeProvider(canned_text="x"), rewriter=rewriter)
    s = Session.new()
    s.add_user("earlier question")  # give history so rewrite WOULD fire if allowed
    handle_turn("totally unrelated astrophysics question here",
                s, Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert calls["n"] == 0  # no rephrase for clearly-out-of-scope
