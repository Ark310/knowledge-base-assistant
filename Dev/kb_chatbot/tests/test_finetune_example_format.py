import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune.example_format import make_example, dumps, loads
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.prompt import build_system_prompt

def _chunk():
    return Chunk(id="ticket_1", text="Problem: X\n\nResolution: do Y",
                 metadata={"kind":"ticket","ticket_id":"1","url":"u","product":"tradedesk"})

def test_make_example_has_three_roles_and_serving_system():
    ex = make_example([_chunk()], "why X?", "Do Y. Sources: [Ticket #1](u)")
    roles = [m["role"] for m in ex["messages"]]
    assert roles == ["system", "user", "assistant"]
    assert ex["messages"][0]["content"] == build_system_prompt()
    assert ex["messages"][2]["content"].startswith("Do Y")

def test_user_turn_matches_serving_context_and_question():
    ex = make_example([_chunk()], "why X?", "ans")
    user = ex["messages"][1]["content"]
    assert "CONTEXT (the only facts you may use):" in user
    assert "USER QUESTION:\nwhy X?" in user

def test_dumps_loads_roundtrip():
    ex = make_example([_chunk()], "q", "a")
    assert loads(dumps(ex)) == ex
