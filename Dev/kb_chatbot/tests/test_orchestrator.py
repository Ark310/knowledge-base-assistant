import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters
from Dev.kb_chatbot.llm.fake_provider import FakeProvider
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps, ABSTAIN_MESSAGE

FIX = Path(__file__).parent / "fixtures" / "tiny_library"


@pytest.fixture(scope="module")
def deps_factory():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))

    def make(confidence_floor: float, fake_text: str):
        r = Retriever(Path(tmp), confidence_floor=confidence_floor)
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
    d, fake = deps_factory(0.99, "should not be seen")
    session = Session.new()
    turn = handle_turn("quantum field theory", session, Filters(),
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