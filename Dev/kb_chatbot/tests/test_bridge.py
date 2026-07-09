import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.bridge import ChatBridge, webui_dir
from Dev.kb_chatbot.chat.session import Turn
from Dev.kb_chatbot.chunker import Chunk


def test_ping():
    assert ChatBridge().ping() == "pong"


def test_providers_json_has_local():
    d = json.loads(ChatBridge().providers())
    assert "local" in d and d["local"]["default_model"] == "contoso-reasoning-qwen25-7b"
    assert "claude" in d and "openai" in d


def test_answer_payload_shapes_turn():
    turn = Turn(role="assistant", kind="answer", content="Fixed it. [Ticket #1](u)",
                citations=[{"raw": "[Ticket #1](u)", "verified": True}],
                retrieved_ids=["ticket_1"], model="m", tokens_in=10, tokens_out=5,
                latency_ms=100)
    ctx = [Chunk(id="ticket_1", text="...", metadata={
        "kind": "ticket", "ticket_id": "1", "title": "Ticket #1", "url": "u",
        "product": "tradedesk", "created_at": "2024-01-01", "resolved": True})]
    p = ChatBridge._answer_payload(turn, ctx)
    assert p["kind"] == "answer"
    assert p["markdown"].startswith("Fixed it")
    assert p["citations"][0]["verified"] is True
    assert p["sources"][0]["ticket_id"] == "1" and p["sources"][0]["url"] == "u"
    assert p["sources"][0]["resolved"] is True
    assert p["debug"]["tokens_out"] == 5 and p["debug"]["model"] == "m"


def test_answer_payload_no_context():
    turn = Turn(role="assistant", kind="abstain", content="No info.", citations=[])
    p = ChatBridge._answer_payload(turn, [])
    assert p["kind"] == "abstain" and p["sources"] == []


def test_webui_dir_points_at_package_webui():
    d = webui_dir()
    assert d.name == "webui" and d.parent.name == "kb_chatbot"
