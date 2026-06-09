import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.prompt import SYSTEM_PROMPT, build_system_prompt, format_context, build_messages
from Dev.kb_chatbot.chunker import Chunk


def test_system_prompt_locked_text_v23():
    p = build_system_prompt()
    assert p == SYSTEM_PROMPT
    assert "Contoso KB articles" in p
    assert "I don't have enough information in the knowledge base" in p
    assert "[Article Title](url)" in p


def test_format_context_uses_url_cite_handle():
    chunks = [
        Chunk(id="x", text="some text",
              metadata={"product": "tradedesk", "category": "dealing",
                        "title": "Booking a Spot Deal",
                        "url": "https://help.contoso.example/display/FX/Booking"})
    ]
    out = format_context(chunks)
    assert "[TradeDesk · dealing · Booking a Spot Deal](https://help.contoso.example/display/FX/Booking)" in out
    assert "some text" in out


def test_format_context_no_url_falls_back_to_plain():
    chunks = [
        Chunk(id="x", text="some text",
              metadata={"product": "tradedesk", "category": "dealing",
                        "title": "Booking a Spot Deal", "url": ""})
    ]
    out = format_context(chunks)
    assert "[TradeDesk · dealing · Booking a Spot Deal]" in out
    assert "some text" in out


def test_format_context_falls_back_to_general_category():
    chunks = [
        Chunk(id="x", text="t",
              metadata={"product": "saleshub", "category": "", "title": "Welcome", "url": ""})
    ]
    out = format_context(chunks)
    assert "[SalesHub · general · Welcome]" in out


def test_format_context_empty_chunks():
    out = format_context([])
    assert "no relevant articles found" in out


def test_build_messages_includes_user_question_and_context():
    chunks = [
        Chunk(id="x", text="content",
              metadata={"product": "web4", "category": "booking_deals",
                        "title": "Quick Pay", "url": "https://help.contoso.example/qp"})
    ]
    msgs = build_messages(context_chunks=chunks, history=[], user_msg="What is Quick Pay?")
    assert msgs[-1]["role"] == "user"
    content = msgs[-1]["content"]
    assert "What is Quick Pay?" in content
    assert "[Web4 · booking_deals · Quick Pay](https://help.contoso.example/qp)" in content


def test_build_messages_includes_history():
    history = [
        {"role": "user", "content": "Earlier?"},
        {"role": "assistant", "content": "Earlier answer."},
    ]
    msgs = build_messages(context_chunks=[], history=history, user_msg="Now?")
    assert msgs[0]["content"] == "Earlier?"
    assert "Now?" in msgs[-1]["content"]


def test_system_prompt_demands_completeness():
    from Dev.kb_chatbot.prompt import build_system_prompt
    p = build_system_prompt().lower()
    assert "all relevant" in p or "every step" in p
    # guardrails still present
    assert "only use facts from the context" in p
    assert "[article title](url)" in p
