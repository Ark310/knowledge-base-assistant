from Dev.kb_chatbot.chat.query_rewriter import (
    build_rewrite_prompt, RewriteResult, REWRITE_MODEL, _clean_response, _usage_value,
)


def test_rewrite_model_is_haiku():
    assert "haiku" in REWRITE_MODEL


def test_usage_value_reads_dict():
    # SDK usage payloads are plain dicts — regression guard for the getattr bug
    assert _usage_value({"input_tokens": 1234, "output_tokens": 56}, "input_tokens") == 1234
    assert _usage_value({"input_tokens": 1234, "output_tokens": 56}, "output_tokens") == 56


def test_usage_value_handles_none_and_missing():
    assert _usage_value(None, "input_tokens") == 0
    assert _usage_value({}, "input_tokens") == 0
    assert _usage_value({"input_tokens": None}, "input_tokens") == 0


def test_prompt_includes_history_and_message():
    history = [
        {"role": "user", "content": "How do I post a deal?"},
        {"role": "assistant", "content": "Which product?"},
    ]
    prompt = build_rewrite_prompt("TradeDesk", history)
    assert "How do I post a deal?" in prompt
    assert "Which product?" in prompt
    assert "TradeDesk" in prompt
    assert "USER:" in prompt and "ASSISTANT:" in prompt


def test_prompt_limits_history_to_last_four_messages():
    history = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    prompt = build_rewrite_prompt("latest", history)
    assert "msg5" not in prompt
    assert "msg9" in prompt


def test_prompt_flattens_multimodal_content():
    history = [{"role": "user", "content": [
        {"type": "image", "source": {}},
        {"type": "text", "text": "what is this error"},
    ]}]
    prompt = build_rewrite_prompt("follow up", history)
    assert "what is this error" in prompt


def test_clean_response_strips_quotes_and_extra_lines():
    assert _clean_response('"posting a retail deal tradedesk"\nextra') == "posting a retail deal tradedesk"


def test_clean_response_empty_returns_empty():
    assert _clean_response("   \n  ") == ""


def test_rewrite_result_fields():
    r = RewriteResult(query="q", tokens_in=10, tokens_out=5, latency_ms=100)
    assert (r.query, r.tokens_in, r.tokens_out, r.latency_ms) == ("q", 10, 5, 100)


from pathlib import Path
from unittest.mock import patch, MagicMock

from Dev.kb_chatbot.chat.session import Session, Turn
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps
from Dev.kb_chatbot.retriever import Retriever, Filters, RetrievalResult
from Dev.kb_chatbot.llm.fake_provider import FakeProvider
from Dev.kb_chatbot.chunker import Chunk


def _ctx_chunk():
    return Chunk(id="c1", text="Deal reversal steps",
                 metadata={"product": "tradedesk", "category": "dealing",
                           "title": "Reverse a Deal", "url": "https://x.com/rev"})


def _mock_retriever(results):
    """Retriever whose retrieve() pops from `results` per call."""
    with patch("Dev.kb_chatbot.retriever.open_persistent_client"), \
         patch("Dev.kb_chatbot.retriever.SentenceTransformer"), \
         patch("Dev.kb_chatbot.retriever.CrossEncoder"):
        r = Retriever(Path("fake"))
    calls = []
    def retrieve(query, filters):
        calls.append(query)
        return results.pop(0)
    r.retrieve = retrieve
    r.retrieve_quick = lambda q, limit=10: []
    r.suggest = lambda q, top_k=5: []
    r._retrieve_calls = calls
    return r


def _session_with_history():
    s = Session.new()
    s.add_user("How do I post a deal in TradeDesk?")
    s.add(Turn(role="assistant", content="Steps...", kind="answer"))
    return s


def test_rewriter_fires_on_abstain_with_history():
    abstain = RetrievalResult(abstain_reason="no_relevant_kb_match", rerank_top_score=0.1)
    success = RetrievalResult(chunks=[_ctx_chunk()], rerank_top_score=0.8)
    r = _mock_retriever([abstain, success])
    rewriter_calls = []
    def fake_rewriter(msg, history):
        rewriter_calls.append(msg)
        from Dev.kb_chatbot.chat.query_rewriter import RewriteResult
        return RewriteResult(query="reverse posted deal tradedesk", tokens_in=200, tokens_out=20, latency_ms=900)
    logged = []
    deps = Deps(retriever=r, llm=FakeProvider(canned_text="Done. [Reverse a Deal](https://x.com/rev)"),
                usage_logger=logged.append, rewriter=fake_rewriter)
    session = _session_with_history()
    turn = handle_turn("undo entire posting flow somehow broken", session, Filters(),
                       "claude-haiku-4-5-20251001", deps=deps)
    assert turn.kind == "answer"
    assert rewriter_calls == ["undo entire posting flow somehow broken"]
    assert r._retrieve_calls[1] == "reverse posted deal tradedesk"
    rewrite_logs = [t for t in logged if t.kind == "rewrite"]
    assert len(rewrite_logs) == 1
    assert rewrite_logs[0].tokens_in == 200


def test_rewriter_not_called_without_history():
    abstain = RetrievalResult(abstain_reason="no_relevant_kb_match", rerank_top_score=0.1)
    r = _mock_retriever([abstain])
    rewriter = MagicMock()
    deps = Deps(retriever=r, llm=FakeProvider(canned_text="x"),
                usage_logger=lambda t: None, rewriter=rewriter)
    turn = handle_turn("some unfindable question here", Session.new(), Filters(),
                       "claude-haiku-4-5-20251001", deps=deps)
    assert turn.kind == "abstain"
    rewriter.assert_not_called()


def test_rewriter_failure_falls_through_to_abstain():
    abstain = RetrievalResult(abstain_reason="no_relevant_kb_match", rerank_top_score=0.1)
    r = _mock_retriever([abstain])
    deps = Deps(retriever=r, llm=FakeProvider(canned_text="x"),
                usage_logger=lambda t: None, rewriter=lambda m, h: None)
    turn = handle_turn("some unfindable question here", _session_with_history(), Filters(),
                       "claude-haiku-4-5-20251001", deps=deps)
    assert turn.kind == "abstain"
    assert len(r._retrieve_calls) == 1  # no retry without a rewrite


def test_rewriter_fires_at_most_once():
    abstain = RetrievalResult(abstain_reason="no_relevant_kb_match", rerank_top_score=0.1)
    r = _mock_retriever([abstain, abstain])
    from Dev.kb_chatbot.chat.query_rewriter import RewriteResult
    rewriter = MagicMock(return_value=RewriteResult(query="better query", tokens_in=1, tokens_out=1, latency_ms=1))
    deps = Deps(retriever=r, llm=FakeProvider(canned_text="x"),
                usage_logger=lambda t: None, rewriter=rewriter)
    turn = handle_turn("some unfindable question here", _session_with_history(), Filters(),
                       "claude-haiku-4-5-20251001", deps=deps)
    assert turn.kind == "abstain"
    assert rewriter.call_count == 1
    assert len(r._retrieve_calls) == 2


def test_progress_callback_invoked_on_rewrite():
    abstain = RetrievalResult(abstain_reason="no_relevant_kb_match", rerank_top_score=0.1)
    success = RetrievalResult(chunks=[_ctx_chunk()], rerank_top_score=0.8)
    r = _mock_retriever([abstain, success])
    from Dev.kb_chatbot.chat.query_rewriter import RewriteResult
    stages = []
    deps = Deps(retriever=r, llm=FakeProvider(canned_text="x"),
                usage_logger=lambda t: None,
                rewriter=lambda m, h: RewriteResult(query="q2", tokens_in=1, tokens_out=1, latency_ms=1),
                on_progress=stages.append)
    handle_turn("some unfindable question here", _session_with_history(), Filters(),
                "claude-haiku-4-5-20251001", deps=deps)
    assert "rephrase" in stages


def test_rewrite_result_has_model_field_default_empty():
    from Dev.kb_chatbot.chat.query_rewriter import RewriteResult
    r = RewriteResult(query="q", tokens_in=1, tokens_out=1, latency_ms=1)
    assert r.model == ""


def test_make_rewriter_claude():
    from Dev.kb_chatbot.chat.query_rewriter import make_rewriter, rewrite_query
    assert make_rewriter("claude") is rewrite_query


def test_make_rewriter_openai():
    from Dev.kb_chatbot.chat.query_rewriter import make_rewriter, rewrite_query_codex
    assert make_rewriter("openai") is rewrite_query_codex


def test_make_rewriter_unknown_defaults_to_claude():
    from Dev.kb_chatbot.chat.query_rewriter import make_rewriter, rewrite_query
    assert make_rewriter("nope") is rewrite_query


def test_rewrite_query_codex_returns_result(monkeypatch):
    from Dev.kb_chatbot.chat import query_rewriter as qr
    monkeypatch.setattr(qr, "_run_codex_exec_for_rewrite",
                        lambda prompt, model: ("reverse posted deal tradedesk", 120, 8))
    out = qr.rewrite_query_codex("undo it", [{"role": "user", "content": "post a deal"}])
    assert out is not None
    assert out.query == "reverse posted deal tradedesk"
    assert out.model == "gpt-5.4-mini"
    assert out.tokens_in == 120 and out.tokens_out == 8


def test_rewrite_query_codex_none_on_failure(monkeypatch):
    from Dev.kb_chatbot.chat import query_rewriter as qr
    def boom(prompt, model):
        raise RuntimeError("codex down")
    monkeypatch.setattr(qr, "_run_codex_exec_for_rewrite", boom)
    assert qr.rewrite_query_codex("undo it", [{"role": "user", "content": "x"}]) is None
