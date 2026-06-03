from Dev.kb_chatbot.prompt import Attachment, build_messages
from Dev.kb_chatbot.chunker import Chunk


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
