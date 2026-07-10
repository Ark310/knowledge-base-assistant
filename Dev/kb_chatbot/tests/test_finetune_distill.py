import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune import distill
from Dev.kb_chatbot.chunker import Chunk

class _StubRetriever:
    def retrieve(self, q, f, top_k_rerank=None):
        class RR: chunks = [Chunk(id="t1", text="Problem: x\n\nResolution: y",
                                  metadata={"kind":"ticket","ticket_id":"1","url":"u","product":"tradedesk"})]
        return RR()
    def get_by_ids(self, ids): return []

def test_distill_one_captures_answer(monkeypatch):
    from Dev.kb_chatbot.chat import orchestrator
    from Dev.kb_chatbot.chat.session import Turn
    monkeypatch.setattr(orchestrator, "handle_turn",
        lambda *a, **k: Turn(role="assistant", kind="answer", content="Cited answer [Ticket #1](u)", retrieved_ids=["t1"]))
    ex = distill.distill_one(_StubRetriever(), object(), "m", "why x?")
    assert ex["messages"][2]["content"].startswith("Cited answer")

def test_distill_one_skips_abstain(monkeypatch):
    from Dev.kb_chatbot.chat import orchestrator
    from Dev.kb_chatbot.chat.session import Turn
    monkeypatch.setattr(orchestrator, "handle_turn",
        lambda *a, **k: Turn(role="assistant", kind="abstain", content="no info"))
    assert distill.distill_one(_StubRetriever(), object(), "m", "q") is None

def test_run_is_resumable(monkeypatch, tmp_path):
    from Dev.kb_chatbot.chat import orchestrator
    from Dev.kb_chatbot.chat.session import Turn
    monkeypatch.setattr(orchestrator, "handle_turn",
        lambda q, *a, **k: Turn(role="assistant", kind="answer", content=f"ans {q}", retrieved_ids=["t1"]))
    out = tmp_path / "distill.jsonl"
    n1 = distill.run(["q1","q2"], _StubRetriever(), object(), "m", out)
    n2 = distill.run(["q1","q2","q3"], _StubRetriever(), object(), "m", out)  # q1,q2 already done
    assert n1 == 2 and n2 == 1
    assert len(out.read_text(encoding="utf-8").strip().splitlines()) == 3

def test_distill_has_cli():
    from Dev.kb_chatbot.finetune import distill
    assert hasattr(distill, "main")
