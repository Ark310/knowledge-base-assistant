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


def test_config_json_shape():
    import json as _j
    d = _j.loads(ChatBridge().config_json())
    assert d["default_provider"] in ("claude", "openai", "local")
    assert "formflow" in d["products"] and d["products"]["formflow"] == "FormFlow"
    assert "local" in d["provider_display"] and "local" in d["models_by_provider"]


# ── bug-169: hung-turn cancel + save-on-send + supersede guard ────────────────

def test_stop_bumps_seq_and_emits_turnstopped():
    b = ChatBridge()
    stopped = []
    b.turnStopped.connect(lambda: stopped.append(1))
    seq0 = b._turn_seq
    b.stop()  # no worker running -> just bump + signal, never wedged
    assert b._turn_seq == seq0 + 1
    assert stopped == [1]


def test_superseded_turn_result_is_dropped():
    # A late result from a stopped/superseded turn must not reach the UI.
    b = ChatBridge()
    failed = []
    b.turnFailed.connect(lambda m: failed.append(m))
    b._turn_seq = 5
    b._on_failed("late error from an abandoned turn", token=3)  # stale token
    assert failed == []
    b._on_failed("current error", token=5)                     # current token
    assert failed == ["current error"]


def test_retire_worker_drops_reference_so_live_qthread_not_gcd():
    # A stopped local call keeps running to timeout; we must retain then retire it,
    # never let self._worker reassignment GC a live QThread (PySide crash).
    b = ChatBridge()

    class FakeWorker:
        def __init__(self):
            self.deleted = False
        def deleteLater(self):
            self.deleted = True

    w = FakeWorker()
    b._workers.append(w)
    b._worker = w
    b._retire_worker(w)
    assert w not in b._workers
    assert b._worker is None
    assert w.deleted is True
