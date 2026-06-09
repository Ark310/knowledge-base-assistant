import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat.session import Session, Turn


def test_session_has_last_rerank_score():
    s = Session.new()
    assert hasattr(s, "last_rerank_score")
    assert s.last_rerank_score == 0.0


def test_session_last_rerank_score_updates():
    s = Session.new()
    s.last_rerank_score = 0.75
    assert s.last_rerank_score == 0.75


def test_turn_has_attachments():
    t = Turn(role="user", content="hello")
    assert hasattr(t, "attachments")
    assert t.attachments == []


def test_turn_attachments_stored():
    t = Turn(role="user", content="hello", attachments=["screenshot.png"])
    assert t.attachments == ["screenshot.png"]


from Dev.kb_chatbot.llm.claude_code_provider import _latest_user_content, _flatten_content


def test_latest_user_content_returns_newest_user_message():
    messages = [
        {"role": "user", "content": "How do I book a deal?"},
        {"role": "assistant", "content": "Navigate to Dealing > New Deal."},
        {"role": "user", "content": "CONTEXT: ...\nUSER QUESTION:\nHow do I reverse that?"},
    ]
    result = _latest_user_content(messages)
    assert "How do I reverse that?" in result
    assert "How do I book a deal?" not in result


def test_latest_user_content_preserves_multimodal_list():
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "abc"}},
        {"type": "text", "text": "What is this?"},
    ]
    messages = [{"role": "user", "content": content}]
    result = _latest_user_content(messages)
    assert result is content  # list passed through untouched, image block intact


def test_flatten_content_extracts_text_from_list():
    content = [
        {"type": "image", "source": {}},
        {"type": "text", "text": "What is this?"},
    ]
    assert _flatten_content(content) == "What is this?"


def test_flatten_content_passthrough_for_string():
    assert _flatten_content("hello") == "hello"


from Dev.kb_chatbot.chat.orchestrator import _is_topic_drift


def test_no_drift_when_previous_score_low():
    assert _is_topic_drift(previous=0.2, current=0.1) is False


def test_no_drift_when_current_score_adequate():
    # Previous is high (>= 0.85) but current is not very low (>= 0.20) → no drift
    assert _is_topic_drift(previous=0.90, current=0.5) is False


def test_drift_detected_when_score_drops_sharply():
    # Previous confident (>= 0.85) and current very low (< 0.20) → drift
    assert _is_topic_drift(previous=0.90, current=0.15) is True


def test_no_drift_at_boundary():
    assert _is_topic_drift(previous=0.5, current=0.20) is False


import tempfile
import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters
from Dev.kb_chatbot.llm.fake_provider import FakeProvider
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps

_FIX = Path(__file__).parent / "fixtures" / "tiny_library"


@pytest.fixture(scope="module")
def _deps_factory_mt():
    tmp = tempfile.mkdtemp()
    ingest(_FIX, Path(tmp))

    def make(confidence_floor: float, fake_text: str):
        r = Retriever(Path(tmp), confidence_floor=confidence_floor)
        llm = FakeProvider(canned_text=fake_text)
        return Deps(retriever=r, llm=llm, usage_logger=lambda t: None), llm
    return make


def test_current_question_not_duplicated_in_messages(_deps_factory_mt):
    """The current user question must appear exactly once in the messages list
    passed to the LLM — not both as a history entry and as the new turn."""
    question = "How do I book a spot deal in TradeDesk?"
    d, fake = _deps_factory_mt(0.0, "Answer [TradeDesk · dealing · Booking a Spot Deal].")
    session = Session.new()
    handle_turn(question, session, Filters(product="tradedesk"),
                "claude-haiku-4-5-20251001", deps=d)

    assert len(fake.calls) >= 1, "Expected at least one LLM call"
    messages = fake.calls[0]["messages"]

    # Count occurrences of the question string across all message content values
    count = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and question in block.get("text", ""):
                    count += 1
        elif question in str(content):
            count += 1

    assert count == 1, (
        f"Expected question to appear exactly once in messages, found {count} times. "
        f"Messages: {messages}"
    )
