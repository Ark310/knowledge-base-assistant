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
