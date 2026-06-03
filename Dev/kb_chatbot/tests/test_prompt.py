import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.prompt import SYSTEM_PROMPT, build_system_prompt, format_context, build_messages
from Dev.kb_chatbot.chunker import Chunk


def test_system_prompt_locked_text_v22():
    p = build_system_prompt()
    assert p == SYSTEM_PROMPT
    assert "Contoso KB articles" in p
    assert "I haven't been trained on this" in p
    assert "[<Product> · <Category> · <Article title>]" in p


def test_format_context_uses_article_cite_handle():
    chunks = [
        Chunk(id="x", text="some text",
              metadata={"product": "tradedesk", "category": "dealing", "title": "Booking a Spot Deal"})
    ]
    out = format_context(chunks)
    assert "[TradeDesk · dealing · Booking a Spot Deal]" in out
    assert "some text" in out


def test_format_context_falls_back_to_general_category():
    chunks = [
        Chunk(id="x", text="t",
              metadata={"product": "saleshub", "category": "", "title": "Welcome"})
    ]
    out = format_context(chunks)
    assert "[SalesHub · general · Welcome]" in out


def test_build_messages_includes_user_question_and_context():
    chunks = [
        Chunk(id="x", text="content",
              metadata={"product": "web4", "category": "booking_deals", "title": "Quick Pay"})
    ]
    msgs = build_messages(context_chunks=chunks, history=[], user_msg="What is Quick Pay?")
    assert msgs[-1]["role"] == "user"
    assert "What is Quick Pay?" in msgs[-1]["content"]
    assert "[Web4 · booking_deals · Quick Pay]" in msgs[-1]["content"]


def test_build_messages_includes_history():
    history = [
        {"role": "user", "content": "Earlier?"},
        {"role": "assistant", "content": "Earlier answer."},
    ]
    msgs = build_messages(context_chunks=[], history=history, user_msg="Now?")
    assert msgs[0]["content"] == "Earlier?"
    assert "Now?" in msgs[-1]["content"]
