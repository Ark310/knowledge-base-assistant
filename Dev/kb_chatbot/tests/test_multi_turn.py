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


from Dev.kb_chatbot.llm.claude_code_provider import _build_user_prompt


def test_build_user_prompt_includes_all_turns():
    messages = [
        {"role": "user", "content": "How do I book a deal?"},
        {"role": "assistant", "content": "Navigate to Dealing > New Deal."},
        {"role": "user", "content": "CONTEXT: ...\nUSER QUESTION:\nHow do I reverse that?"},
    ]
    result = _build_user_prompt(messages)
    assert "How do I book a deal?" in result
    assert "Navigate to Dealing" in result
    assert "How do I reverse that?" in result


def test_build_user_prompt_handles_list_content():
    messages = [
        {"role": "user", "content": [
            {"type": "image", "source": {}},
            {"type": "text", "text": "What is this?"},
        ]},
    ]
    result = _build_user_prompt(messages)
    assert "What is this?" in result


from Dev.kb_chatbot.chat.orchestrator import _is_topic_drift


def test_no_drift_when_previous_score_low():
    assert _is_topic_drift(previous=0.2, current=0.1) is False


def test_no_drift_when_current_score_adequate():
    assert _is_topic_drift(previous=0.8, current=0.5) is False


def test_drift_detected_when_score_drops_sharply():
    assert _is_topic_drift(previous=0.7, current=0.15) is True


def test_no_drift_at_boundary():
    assert _is_topic_drift(previous=0.5, current=0.20) is False
