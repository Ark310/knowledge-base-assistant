import json
from pathlib import Path
from Dev.kb_chatbot.ticket_ingest import build_ticket_chunks


def _ticket(tmp, comments, resolution=None, **over):
    """New tradedesk schema: comments have {author, body, date, internal}; resolution
    is {text, attachments, comments}. All values below are synthetic (no real PII)."""
    data = {"title": "URGENT | CAB FixApp", "product": "TD Client Server",
            "organization": "Fabrikam Financial", "category": "Question",
            "created_by": "srivera", "assignee": "Taylor.Brooks", "status": "Closed",
            "csqa_owner": "p.shah", "ticket_id": "75100",
            "url": "https://portal.contoso.example/tickets/75100/edit",
            "resolution_url": "https://portal.contoso.example/tickets/75100/edit",
            "comments": comments,
            "resolution": resolution if resolution is not None
            else {"text": "", "attachments": [], "comments": []}}
    data.update(over)
    p = Path(tmp) / "ticket_75100.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return data, p


def test_resolution_from_resolution_text(tmp_path):
    data, p = _ticket(tmp_path,
        [{"author": "srivera", "body": "We are not getting prices from CAB.", "internal": False}],
        resolution={"text": "FixApp session has been restarted", "attachments": [], "comments": []})
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) == 1
    c = chunks[0]
    assert "FixApp session has been restarted" in c.text
    assert c.metadata["resolved"] is True
    assert c.metadata["kind"] == "ticket"
    assert c.metadata["ticket_id"] == "75100"
    assert c.metadata["url"] == data["url"]
    assert c.metadata["title"] == "Ticket #75100"


def test_resolution_from_internal_comment(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "prices missing", "internal": False},
        {"author": "Taylor.Brooks", "body": "Restarted the FixApp session; resolved.", "internal": True},
    ])
    c = build_ticket_chunks(data, p)[0]
    assert "Restarted the FixApp session" in c.text
    assert c.metadata["resolved"] is True


def test_no_resolution_indexes_problem_only(tmp_path):
    data, p = _ticket(tmp_path,
        [{"author": "srivera", "body": "Customer asking a question", "internal": False}])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) == 1                       # NOT skipped anymore
    assert chunks[0].metadata["resolved"] is False
    assert "[UNRESOLVED]" in chunks[0].text
    assert "Customer asking a question" in chunks[0].text


def test_chunk_text_has_no_pii(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera",
         "body": "Hi, From Sam Rivera sam.rivera@fabrikam.example: prices missing. Regards Sam",
         "internal": False},
    ], resolution={"text": "Restarted the session for the client", "attachments": [], "comments": []})
    c = build_ticket_chunks(data, p)[0]
    assert "@" not in c.text
    assert "Sam" not in c.text
    assert "fabrikam.example" not in c.text.lower()   # email domain stripped
    assert "Client: Fabrikam Financial" in c.text     # client company surfaced (field-derived header)


def test_stable_id(tmp_path):
    data, p = _ticket(tmp_path, [{"author": "x", "body": "prob", "internal": False}],
                      resolution={"text": "resolved", "attachments": [], "comments": []})
    a = build_ticket_chunks(data, p)[0].id
    b = build_ticket_chunks(data, p)[0].id
    assert a == b and a.startswith("ticket_")


def test_header_surfaces_team_and_client(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "prices missing, please fix", "internal": False},
        {"author": "jchen", "body": "Restarted the session", "internal": True},
    ], resolution={"text": "Fixed on LIVE", "attachments": [], "comments": []},
       csqa_owner="p.shah", sqa_assignee="jchen", site1_qa_signoff="jchen", site2_qa_signoff="p.shah")
    c = build_ticket_chunks(data, p)[0]
    assert "Client: Fabrikam Financial" in c.text
    assert "CSQA owner: p.shah" in c.text
    assert "Assignee: Taylor.Brooks" in c.text
    assert "Handled by:" in c.text and "jchen" in c.text
    assert c.metadata["csqa_owner"] == "p.shah"
    assert c.metadata["organization"] == "Fabrikam Financial"


def test_handled_by_excludes_created_by(tmp_path):
    from Dev.kb_chatbot.ticket_ingest import _handled_by
    data, p = _ticket(tmp_path, [{"author": "srivera", "body": "resolved", "internal": True}],
                      created_by="srivera")
    assert "srivera" not in _handled_by(data)


def test_handled_by_collects_internal_authors(tmp_path):
    from Dev.kb_chatbot.ticket_ingest import _handled_by
    data, p = _ticket(tmp_path, [
        {"author": "customerX", "body": "broke", "internal": False},
        {"author": "jchen", "body": "done", "internal": True},
    ])
    h = _handled_by(data)
    assert "jchen" in h and "customerX" not in h


def test_known_terms_excludes_stopwords_and_org():
    from Dev.kb_chatbot.ticket_ingest import _known_terms
    terms = {t.lower() for t in _known_terms({
        "organization": "Litware", "created_by": "", "assignee": "",
        "comments": [{"author": "a", "body": "Thanks for the update from the bank", "internal": True}],
        "resolution": {"text": "", "comments": []}})}
    assert "for" not in terms and "the" not in terms and "update" not in terms
    assert "litware" not in terms                 # org intentionally not redacted


def test_short_ticket_single_chunk(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "Login fails with error 500.", "internal": False},
        {"author": "a.user", "body": "Cleared the cache; resolved.", "internal": True},
    ])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) == 1
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[0].metadata["has_images"] is False
    assert "Problem:" in chunks[0].text and "Resolution:" in chunks[0].text


def test_long_ticket_multi_chunk_shares_ticket_id(tmp_path):
    big = " ".join(f"step{i} do the thing carefully" for i in range(300))
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "It broke.", "internal": False},
        {"author": "a.user", "body": big, "internal": True},
    ])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) > 1
    assert all(c.metadata["ticket_id"] == "75100" for c in chunks)
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert all(c.text.startswith("Ticket #75100") for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)


def test_has_images_flag_from_comment_images(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "See screenshot.", "internal": False,
         "images": [{"mime": "image/png", "saved_path": "attachments/75100/c1.png"}]},
        {"author": "a.user", "body": "Fixed per the image.", "internal": True},
    ])
    chunks = build_ticket_chunks(data, p)
    assert all(c.metadata["has_images"] is True for c in chunks)


def test_real_corpus_no_email_leak_if_present():
    # Adversarial smoke over any real tickets present locally (git-ignored). Skips if none.
    # Checks for a REAL email (localpart@domain.tld), NOT a bare '@' — the redactor
    # legitimately leaves '@[redacted]' for social handles (cerebrum: leak checks must
    # exclude the redactor's own placeholder).
    import glob, re
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    for fp in glob.glob("library/tickets/ticket_*.json")[:50]:
        data = json.loads(Path(fp).read_text(encoding="utf-8"))
        for c in build_ticket_chunks(data, Path(fp)):
            assert not email.search(c.text), f"{fp}: real email pattern leaked in a chunk"


from Dev.kb_chatbot.ticket_ingest import _parse_created_at


def test_parse_created_at_formats():
    assert _parse_created_at("2024-08-22 6:37 AM") == "2024-08-22"
    assert _parse_created_at("2026-04-23 5:41 AM") == "2026-04-23"
    assert _parse_created_at("") == ""
    assert _parse_created_at("garbage") == ""


def test_chunk_has_recency_and_normalized_product(tmp_path):
    data, p = _ticket(tmp_path, [
        {"author": "srivera", "body": "It broke.", "internal": False},
        {"author": "a.user", "body": "Fixed it.", "internal": True},
    ], product="FormFlow", created_at="2024-08-22 6:37 AM")
    m = build_ticket_chunks(data, p)[0].metadata
    assert m["product"] == "formflow"
    assert m["project"] == "FormFlow"
    assert m["created_at"] == "2024-08-22"
    assert "Date: 2024-08-22" in build_ticket_chunks(data, p)[0].text
