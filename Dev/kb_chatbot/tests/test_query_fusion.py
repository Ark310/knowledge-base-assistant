from Dev.kb_chatbot.chat.session import Session, Turn


def _session_with(*turns) -> Session:
    s = Session.new()
    for role, content, kind in turns:
        if role == "user":
            s.add_user(content)
        else:
            s.add(Turn(role="assistant", content=content, kind=kind))
    return s


def test_last_user_question_empty_session():
    assert Session.new().last_user_question() == ""


def test_last_user_question_returns_newest():
    s = _session_with(("user", "first q", "user"),
                      ("assistant", "answer", "answer"),
                      ("user", "second q", "user"))
    assert s.last_user_question() == "second q"


def test_last_assistant_kind_empty_session():
    assert Session.new().last_assistant_kind() == ""


def test_last_assistant_kind_returns_newest():
    s = _session_with(("user", "q", "user"),
                      ("assistant", "which product?", "clarification"))
    assert s.last_assistant_kind() == "clarification"


def test_last_assistant_kind_skips_user_turns():
    s = _session_with(("user", "q", "user"),
                      ("assistant", "ans", "answer"),
                      ("user", "follow", "user"))
    assert s.last_assistant_kind() == "answer"


from Dev.kb_chatbot.chat.orchestrator import _build_retrieval_query, _extract_single_product


def test_extract_single_product():
    assert _extract_single_product("TradeDesk please") == "tradedesk"
    assert _extract_single_product("the api one") == "api"


def test_extract_no_product():
    assert _extract_single_product("the first option") is None


def test_extract_multiple_products_returns_none():
    assert _extract_single_product("tradedesk or web2?") is None


def test_extract_requires_whole_word():
    # 'rapid' must not match 'api'; 'another' must not match 'other'
    assert _extract_single_product("rapid deal entry") is None
    assert _extract_single_product("try another approach") is None
    assert _extract_single_product("capital markets") is None


def test_fusion_raw_passthrough_no_history():
    s = Session.new()
    q, product = _build_retrieval_query(s, "How do I post a deal?")
    assert q == "How do I post a deal?"
    assert product is None


def test_fusion_clarification_reply_combines_and_extracts_product():
    s = _session_with(("user", "How do I post a deal?", "user"),
                      ("assistant", "Which product?", "clarification"))
    q, product = _build_retrieval_query(s, "TradeDesk")
    assert q == "How do I post a deal? TradeDesk"
    assert product == "tradedesk"


def test_fusion_clarification_reply_without_product():
    s = _session_with(("user", "How do I post a deal?", "user"),
                      ("assistant", "Which product?", "clarification"))
    q, product = _build_retrieval_query(s, "the retail one")
    assert q == "How do I post a deal? the retail one"
    assert product is None


def test_fusion_short_followup_combines():
    s = _session_with(("user", "How do I post a deal in TradeDesk?", "user"),
                      ("assistant", "Steps: ...", "answer"))
    q, product = _build_retrieval_query(s, "how to reverse it?")
    assert q == "How do I post a deal in TradeDesk? how to reverse it?"
    assert product is None


def test_fusion_long_message_passthrough():
    s = _session_with(("user", "How do I post a deal?", "user"),
                      ("assistant", "Steps: ...", "answer"))
    msg = "What are the compliance requirements for posting a new retail deal?"
    q, product = _build_retrieval_query(s, msg)
    assert q == msg
    assert product is None
