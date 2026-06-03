import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.prompt import format_suggestions, build_messages
from Dev.kb_chatbot.chunker import Chunk


def _chunk(title, url, product="tradedesk", category="dealing"):
    return Chunk(
        id="x", text="content",
        metadata={"product": product, "category": category, "title": title, "url": url},
    )


def test_format_suggestions_produces_markdown_links():
    chunks = [
        _chunk("Book a Retail Deal", "https://help.contoso.example/deal"),
        _chunk("Deal Types", "https://help.contoso.example/types"),
    ]
    result = format_suggestions(chunks)
    assert "[Book a Retail Deal](https://help.contoso.example/deal)" in result
    assert "[Deal Types](https://help.contoso.example/types)" in result


def test_format_suggestions_empty_returns_empty():
    assert format_suggestions([]) == ""


def test_build_messages_includes_url_in_context():
    chunk = _chunk("Book a Retail Deal", "https://help.contoso.example/deal")
    msgs = build_messages(context_chunks=[chunk], history=[], user_msg="How?")
    last_content = msgs[-1]["content"]
    assert "https://help.contoso.example/deal" in last_content


def test_build_messages_text_attachment_prepended():
    from Dev.kb_chatbot.prompt import Attachment
    chunk = _chunk("Book a Retail Deal", "https://help.contoso.example/deal")
    att = Attachment(filename="notes.txt", media_type="text/plain",
                     data=b"some log content", is_image=False)
    msgs = build_messages(context_chunks=[chunk], history=[], user_msg="Why?",
                          attachments=[att])
    last_content = msgs[-1]["content"]
    assert "[Attached: notes.txt]" in last_content
    assert "some log content" in last_content


def test_build_messages_image_attachment_creates_list_content():
    from Dev.kb_chatbot.prompt import Attachment
    chunk = _chunk("Book a Retail Deal", "https://help.contoso.example/deal")
    att = Attachment(filename="screen.png", media_type="image/png",
                     data=b"\x89PNG", is_image=True)
    msgs = build_messages(context_chunks=[chunk], history=[], user_msg="What is this?",
                          attachments=[att])
    last_content = msgs[-1]["content"]
    assert isinstance(last_content, list)
    types = [b["type"] for b in last_content]
    assert "image" in types
    assert "text" in types


# ── Task 6: Retriever.suggest() ───────────────────────────────────────────────
from unittest.mock import MagicMock, patch
from Dev.kb_chatbot.retriever import Retriever, Filters


def _make_retriever_with_mock_chroma(chunks):
    """Build a Retriever with mocked ChromaDB and embedding models."""
    with patch("Dev.kb_chatbot.retriever.chromadb.PersistentClient"), \
         patch("Dev.kb_chatbot.retriever.SentenceTransformer"), \
         patch("Dev.kb_chatbot.retriever.CrossEncoder"):
        r = Retriever(Path("fake_chroma"))
    r._embed = lambda text: [0.1] * 384
    r._query_chroma = MagicMock(return_value=chunks)
    return r


def test_suggest_returns_chunks():
    chunks = [
        _chunk("A", "https://x.com/a"),
        _chunk("B", "https://x.com/b"),
    ]
    r = _make_retriever_with_mock_chroma(chunks)
    results = r.suggest("how to book")
    assert len(results) == 2


def test_suggest_deduplicates_by_title():
    a1 = _chunk("A", "https://x.com/a")
    a2 = _chunk("A", "https://x.com/a")
    b = _chunk("B", "https://x.com/b")
    r = _make_retriever_with_mock_chroma([a1, a2, b])
    results = r.suggest("how to book")
    titles = [c.metadata["title"] for c in results]
    assert titles.count("A") == 1


def test_suggest_caps_at_top_k():
    chunks = [_chunk(f"T{i}", f"https://x.com/{i}") for i in range(12)]
    r = _make_retriever_with_mock_chroma(chunks)
    results = r.suggest("query", top_k=5)
    assert len(results) == 5


# ── Task 7: Orchestrator — short-query clarification + abstain templates ──────
from Dev.kb_chatbot.chat.orchestrator import (
    _is_short_unspecified_query, ABSTAIN_WITH_SUGGESTIONS_TEMPLATE,
)


def test_short_query_detected():
    assert _is_short_unspecified_query("deal") is True
    assert _is_short_unspecified_query("hi") is True


def test_long_query_not_short():
    assert _is_short_unspecified_query("How do I book a retail deal in TradeDesk?") is False


def test_product_named_query_not_unspecified():
    assert _is_short_unspecified_query("tradedesk deal") is False


def test_abstain_template_exists():
    assert "related" in ABSTAIN_WITH_SUGGESTIONS_TEMPLATE.lower()
