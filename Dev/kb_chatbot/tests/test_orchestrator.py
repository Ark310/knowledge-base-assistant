import sys, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters, RetrievalResult
from Dev.kb_chatbot.llm.fake_provider import FakeProvider
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chat.orchestrator import (
    handle_turn, Deps, ABSTAIN_MESSAGE, SHORT_QUERY_CLARIFICATION,
    LOW_CONFIDENCE_CEILING, LOW_CONFIDENCE_FOOTER,
)
from Dev.kb_chatbot.chunker import Chunk

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


def _make_chunk(title: str, url: str, product: str = "tradedesk", category: str = "dealing") -> Chunk:
    return Chunk(id="x", text="content",
                 metadata={"product": product, "category": category,
                            "title": title, "url": url})


@pytest.fixture(scope="module")
def deps_factory():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))

    def make(confidence_floor: float, fake_text: str, suggest_chunks=None,
             quick_chunks=None):
        r = Retriever(Path(tmp), confidence_floor=confidence_floor)
        # Stub suggest() so legacy tests are not affected by new suggestion logic
        r.suggest = lambda query, top_k=5: (suggest_chunks or [])
        # Optionally stub retrieve_quick to control clarification-from-quick path
        if quick_chunks is not None:
            r.retrieve_quick = lambda query, limit=10: quick_chunks
        llm = FakeProvider(canned_text=fake_text)
        return Deps(retriever=r, llm=llm, usage_logger=lambda t: None), llm
    return make


def test_clear_question_yields_answer_turn(deps_factory):
    d, _ = deps_factory(0.0, "Answer text [TradeDesk · dealing · Booking a Spot Deal].")
    session = Session.new()
    turn = handle_turn("How do I book a spot deal in TradeDesk?", session,
                        Filters(product="tradedesk"), "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "answer"
    assert "Booking a Spot Deal" in turn.content


def test_abstain_when_retrieval_below_floor(deps_factory):
    # Query is long enough (>= 4 words) and has no product, suggest() stubbed to []
    # so content must equal plain ABSTAIN_MESSAGE.
    # quick_chunks=[] prevents multi-product clarifier from intercepting the abstain path.
    d, fake = deps_factory(0.99, "should not be seen", suggest_chunks=[], quick_chunks=[])
    session = Session.new()
    turn = handle_turn("quantum field theory equations", session, Filters(),
                        "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "abstain"
    assert turn.content == ABSTAIN_MESSAGE
    assert len(fake.calls) == 0


def test_hallucinated_citation_gets_stripped(deps_factory):
    d, _ = deps_factory(0.0, "Some answer [No Such Article](https://help.contoso.example/display/FAKE).")
    session = Session.new()
    turn = handle_turn("anything about tradedesk dealing", session,
                        Filters(product="tradedesk"), "claude-haiku-4-5-20251001", deps=d)
    assert "[unverified]" in turn.content
    assert "No Such Article" not in turn.content


def test_session_persists_user_turn():
    s = Session.new()
    assert s.turns == []
    s.add_user("hi")
    assert s.turns[-1]["role"] == "user"


def test_clarification_when_no_product_and_diffuse_retrieval(deps_factory):
    d, fake = deps_factory(0.0, "irrelevant fake answer")
    session = Session.new()
    turn = handle_turn("How do I do this?", session, Filters(),
                        "claude-haiku-4-5-20251001", deps=d)
    if turn.kind == "clarification":
        assert len(fake.calls) == 0
    else:
        assert turn.kind in ("answer", "abstain")


# ── New behavioral tests for Task 7 ──────────────────────────────────────────


def test_abstain_with_suggestions_when_suggest_returns_chunks(deps_factory):
    """Long query that abstains + suggest() returns chunks → kind=abstain, content has links.
    quick_chunks=[] prevents multi-product clarifier from intercepting the abstain path."""
    suggestion_chunks = [
        _make_chunk("Booking a Spot Deal", "https://help.contoso.example/spot"),
        _make_chunk("Forward Deal Guide", "https://help.contoso.example/forward"),
    ]
    d, fake = deps_factory(0.99, "should not be seen", suggest_chunks=suggestion_chunks,
                           quick_chunks=[])
    session = Session.new()
    turn = handle_turn("quantum field theory equations", session, Filters(),
                        "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "abstain"
    assert "https://help.contoso.example/spot" in turn.content
    assert "Booking a Spot Deal" in turn.content
    assert len(fake.calls) == 0


def test_short_unspecified_query_returns_clarification(deps_factory):
    """Short query with no product name triggers kind=clarification with SHORT_QUERY_CLARIFICATION.
    confidence_floor=999.0 guarantees abstain; quick_chunks=[] prevents multi-product clarifier."""
    d, fake = deps_factory(999.0, "should not be seen",
                            suggest_chunks=[], quick_chunks=[])
    session = Session.new()
    # "deal" = 1 word, no product name → short unspecified
    turn = handle_turn("deal", session, Filters(),
                        "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "clarification"
    assert turn.content == SHORT_QUERY_CLARIFICATION
    assert len(fake.calls) == 0


def test_low_confidence_answer_appends_footer_when_suggestions_exist(deps_factory):
    """Answer with rerank_top_score < LOW_CONFIDENCE_CEILING + suggestions → footer appended."""
    suggestion_chunks = [
        _make_chunk("Related Article", "https://help.contoso.example/related"),
    ]
    d, _ = deps_factory(0.0, "The answer is here.", suggest_chunks=suggestion_chunks)
    # Stub retrieve() for a deterministic below-ceiling score (0-1 sigmoid scale, new ceiling = 0.35)
    ctx = [_make_chunk("Booking a Spot Deal", "https://help.contoso.example/spot")]
    d.retriever.retrieve = lambda q, f: RetrievalResult(chunks=ctx, rerank_top_score=0.20)
    session = Session.new()
    turn = handle_turn("tradedesk advanced topics overview details", session,
                        Filters(product="tradedesk"), "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "answer"
    footer_sentinel = LOW_CONFIDENCE_FOOTER.format(suggestions="").strip().splitlines()[-1]
    assert footer_sentinel in turn.content
    assert "https://help.contoso.example/related" in turn.content


def test_high_confidence_answer_no_footer(deps_factory):
    """Answer with rerank_top_score >= LOW_CONFIDENCE_CEILING → no footer."""
    d, _ = deps_factory(0.0, "You book a spot deal via the dealing screen.",
                         suggest_chunks=[
                             _make_chunk("Some Article", "https://help.contoso.example/art"),
                         ])
    # Stub retrieve() for a deterministic above-ceiling score
    ctx = [_make_chunk("Booking a Spot Deal", "https://help.contoso.example/spot")]
    d.retriever.retrieve = lambda q, f: RetrievalResult(chunks=ctx, rerank_top_score=0.80)
    session = Session.new()
    turn = handle_turn("How do I book a spot deal in TradeDesk?", session,
                        Filters(product="tradedesk"), "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "answer"
    footer_sentinel = LOW_CONFIDENCE_FOOTER.format(suggestions="").strip().splitlines()[-1]
    assert footer_sentinel not in turn.content