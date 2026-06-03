import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.prompt import Attachment, build_messages
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.retriever import Retriever, Filters, RetrievalResult
from Dev.kb_chatbot.llm.fake_provider import FakeProvider
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps
from Dev.kb_chatbot.ingest import ingest

_FIX = Path(__file__).parent / "fixtures" / "tiny_library"


def _chunk():
    return Chunk(id="x", text="content",
                 metadata={"title": "Art", "url": "https://x.com", "product": "tradedesk", "category": "dealing"})


def test_text_attachment_included_in_message():
    att = Attachment(filename="notes.txt", media_type="text/plain",
                     data=b"log line 1\nlog line 2", is_image=False)
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="Why?",
                          attachments=[att])
    content = msgs[-1]["content"]
    assert isinstance(content, str)
    assert "log line 1" in content


def test_text_attachment_truncated_at_20000_chars():
    long_data = ("x" * 21_000).encode()
    att = Attachment(filename="big.txt", media_type="text/plain",
                     data=long_data, is_image=False)
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="?",
                          attachments=[att])
    content = msgs[-1]["content"]
    assert "[truncated]" in content
    assert content.count("x") <= 20_050  # truncated body, small allowance for other text


def test_image_attachment_produces_list_content():
    att = Attachment(filename="screen.png", media_type="image/png",
                     data=b"\x89PNG\r\n\x1a\n", is_image=True)
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="What?",
                          attachments=[att])
    content = msgs[-1]["content"]
    assert isinstance(content, list)
    image_blocks = [b for b in content if b.get("type") == "image"]
    text_blocks = [b for b in content if b.get("type") == "text"]
    assert len(image_blocks) == 1
    assert len(text_blocks) == 1


def test_image_block_has_base64_data():
    import base64
    raw = b"\x89PNG\r\n"
    att = Attachment(filename="s.png", media_type="image/png", data=raw, is_image=True)
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="?",
                          attachments=[att])
    content = msgs[-1]["content"]
    img_block = next(b for b in content if b["type"] == "image")
    assert img_block["source"]["type"] == "base64"
    assert img_block["source"]["data"] == base64.b64encode(raw).decode()


def test_no_attachments_produces_string_content():
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="How?")
    assert isinstance(msgs[-1]["content"], str)


def test_multiple_attachments_mixed():
    atts = [
        Attachment(filename="a.txt", media_type="text/plain", data=b"text-a", is_image=False),
        Attachment(filename="b.png", media_type="image/png", data=b"img-b", is_image=True),
        Attachment(filename="c.txt", media_type="text/plain", data=b"text-c", is_image=False),
    ]
    msgs = build_messages(context_chunks=[_chunk()], history=[], user_msg="?",
                          attachments=atts)
    content = msgs[-1]["content"]
    assert isinstance(content, list)
    text_block = next(b for b in content if b["type"] == "text")
    assert "text-a" in text_block["text"]
    assert "text-c" in text_block["text"]
    assert len([b for b in content if b["type"] == "image"]) == 1


# ── Orchestrator behavioral test: attachments flow through handle_turn ────────

def test_attachment_filenames_recorded_on_answer_turn():
    """Attachments in Deps reach build_messages (LLM receives an image block)
    and the returned Turn records the filename."""
    tmp = tempfile.mkdtemp()
    ingest(_FIX, Path(tmp))
    r = Retriever(Path(tmp), confidence_floor=0.0)
    # Stub suggest() so the suggestion-footer logic is not a confounder
    r.suggest = lambda query, top_k=5: []
    # Stub retrieve() to return a deterministic result above the abstain floor
    ctx = [Chunk(id="x", text="content",
                 metadata={"title": "Booking a Spot Deal",
                            "url": "https://help.contoso.example/spot",
                            "product": "tradedesk", "category": "dealing"})]
    r.retrieve = lambda q, f: RetrievalResult(chunks=ctx, rerank_top_score=0.9)

    fake = FakeProvider(canned_text="You book via the dealing screen [Booking a Spot Deal](https://help.contoso.example/spot).")
    att = Attachment(filename="screenshot.png", media_type="image/png",
                     data=b"\x89PNG\r\n\x1a\n", is_image=True)
    deps = Deps(retriever=r, llm=fake, usage_logger=lambda t: None,
                attachments=[att])

    session = Session.new()
    turn = handle_turn("How do I book a spot deal in TradeDesk?", session,
                       Filters(product="tradedesk"), "claude-haiku-4-5-20251001", deps=deps)

    # The answer Turn must record the attachment filename
    assert turn.attachments == ["screenshot.png"]

    # The FakeProvider must have been called exactly once
    assert len(fake.calls) == 1

    # The message content reaching the LLM must be a list (image + text blocks)
    last_user_msg = fake.calls[0]["messages"][-1]
    assert isinstance(last_user_msg["content"], list), \
        "Expected image content list; got plain string — attachments not passed to build_messages"
    image_blocks = [b for b in last_user_msg["content"] if b.get("type") == "image"]
    assert len(image_blocks) == 1, "Expected exactly 1 image block in the LLM message"
