import json
from pathlib import Path
from Dev.kb_chatbot.ticket_ingest import build_ticket_chunks


def _ticket(tmp, comments, **over):
    data = {"title": "URGENT | CAB FixApp", "product": "TD Client Server",
            "organization": "Fabrikam Financial", "category": "Question",
            "created_by": "srivera", "assignee": "Taylor.Brooks", "status": "Closed",
            "ticket_id": "75100", "url": "https://support.contoso.example/edit_bug.aspx?id=75100",
            "resolution_url": "https://support.contoso.example/Resolution.aspx?bugid=75100",
            "comments": comments}
    data.update(over)
    p = Path(tmp) / "ticket_75100.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return data, p


def test_chunk_has_problem_and_resolution(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "unknown", "body": "We are not getting prices from CAB. Please restart FixApp."},
        {"type": "comment", "author": "Taylor.Brooks", "body": "FixApp session has been restarted"},
    ])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) == 1
    c = chunks[0]
    assert "FixApp session has been restarted" in c.text
    assert c.metadata["kind"] == "ticket"
    assert c.metadata["ticket_id"] == "75100"
    assert c.metadata["url"] == data["url"]
    assert c.metadata["resolution_url"] == data["resolution_url"]
    assert c.metadata["title"] == "Ticket #75100"


def test_chunk_text_has_no_pii(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "unknown",
         "header": "email received from Sam Rivera sam.rivera@fabrikam.example",
         "body": "Hi, From Sam Rivera sam.rivera@fabrikam.example: prices missing. Regards Sam"},
        {"type": "comment", "author": "Taylor.Brooks", "body": "Restarted the session for Fabrikam Financial"},
    ])
    c = build_ticket_chunks(data, p)[0]
    assert "@" not in c.text                       # emails still stripped
    assert "Sam" not in c.text                    # external customer personal name stripped
    assert "fabrikam" not in c.text.lower()   # email domain stripped
    assert "Client: Fabrikam Financial" in c.text      # client company name now surfaced


def test_no_resolution_skipped(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "unknown", "body": "Customer asking a question"},
    ])
    assert build_ticket_chunks(data, p) == []


def test_stable_id(tmp_path):
    data, p = _ticket(tmp_path, [{"type": "comment", "author": "x", "body": "resolved"}])
    a = build_ticket_chunks(data, p)[0].id
    b = build_ticket_chunks(data, p)[0].id
    assert a == b and a.startswith("ticket_")


def test_gather_ticket_jsons(tmp_path):
    import json as _j
    tickets = tmp_path / "tickets"; tickets.mkdir()
    (tickets / "ticket_1.json").write_text(_j.dumps({"title": "T"}), encoding="utf-8")
    (tickets / "index.json").write_text("{}", encoding="utf-8")
    from Dev.kb_chatbot.ingest import _gather_ticket_jsons
    found = _gather_ticket_jsons(tickets)
    assert len(found) == 1 and found[0].name == "ticket_1.json"


def test_real_ticket_chunks_no_pii():
    # Adversarial: real corpus through the full build_ticket_chunks pipeline
    for tid in ("75100", "75103", "75111"):
        p = Path(f"library/tickets/ticket_{tid}.json")
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        chunks = build_ticket_chunks(data, p)
        for c in chunks:
            assert "@" not in c.text, f"{tid}: email leaked"


def test_resolution_not_over_redacted():
    import json
    from pathlib import Path
    p = Path("library/tickets/ticket_75100.json")
    data = json.loads(p.read_text(encoding="utf-8"))
    chunks = build_ticket_chunks(data, p)
    assert chunks
    text = chunks[0].text
    # The staff resolution must retain its real words, not be mostly [redacted]
    assert "FixApp session has been restarted" in text
    # Sanity: redaction markers should be a small fraction, not dominate
    assert text.count("[redacted]") <= 3


def test_known_terms_excludes_stopwords():
    from Dev.kb_chatbot.ticket_ingest import _known_terms
    terms = _known_terms({"organization": "", "created_by": "", "assignee": "",
                          "comments": [{"type": "unknown",
                                        "body": "Thanks for the update from the bank"}]})
    lows = {t.lower() for t in terms}
    assert "for" not in lows and "the" not in lows and "update" not in lows


def test_chunk_header_surfaces_team_and_client(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "unknown", "body": "prices missing, please fix"},
        {"type": "comment", "author": "jchen", "body": "Restarted the session"},
        {"type": "unknown",
         "header": "email 1 sent to A Customer <c@client.com> by mlopez on 2023-01-01"},
    ], csqa_owner="p.shah", sqa_assignee="jchen", site1_qa_signoff="jchen",
       site2_qa_signoff="p.shah")
    c = build_ticket_chunks(data, p)[0]
    assert "Client: Fabrikam Financial" in c.text
    assert "CSQA owner: p.shah" in c.text
    assert "Assignee: Taylor.Brooks" in c.text
    assert "Handled by:" in c.text and "jchen" in c.text and "mlopez" in c.text
    assert c.metadata["csqa_owner"] == "p.shah"
    assert c.metadata["organization"] == "Fabrikam Financial"
    assert c.metadata["url"] == data["url"]


def test_handled_by_excludes_created_by(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "comment", "author": "srivera", "body": "resolved"},
    ], created_by="srivera")
    from Dev.kb_chatbot.ticket_ingest import _handled_by
    assert "srivera" not in _handled_by(data)


def test_known_terms_excludes_organization():
    from Dev.kb_chatbot.ticket_ingest import _known_terms
    terms = {t.lower() for t in _known_terms(
        {"organization": "Litware", "created_by": "", "assignee": "", "comments": []})}
    assert "litware" not in terms


def test_handled_by_ignores_header_noise(tmp_path):
    from Dev.kb_chatbot.ticket_ingest import _handled_by
    data, p = _ticket(tmp_path, [
        {"type": "unknown", "header": "email 9 sent to A Customer <c@x.com> by email on 2023-01-01"},
        {"type": "comment", "author": "jchen", "body": "done"},
    ])
    h = _handled_by(data)
    assert "email" not in [x.lower() for x in h]
    assert "jchen" in h


def test_greeting_modal_not_harvested_as_term():
    from Dev.kb_chatbot.ticket_ingest import _known_terms
    data = {"comments": [{"type": "comment", "author": "a.user",
                          "header": "", "body": "Thanks. Could you re-run the batch?"}]}
    terms = _known_terms(data)
    assert "Could" not in terms and "could" not in [t.lower() for t in terms]


def test_short_ticket_single_chunk(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "email", "header": "", "body": "Login fails with error 500."},
        {"type": "comment", "author": "a.user", "header": "", "body": "Cleared the cache; resolved."},
    ])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) == 1
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[0].metadata["has_images"] is False
    assert "Problem:" in chunks[0].text and "Resolution:" in chunks[0].text


def test_long_ticket_multi_chunk_shares_ticket_id(tmp_path):
    big = " ".join(f"step{i} do the thing carefully" for i in range(300))  # ~1500 words
    data, p = _ticket(tmp_path, [
        {"type": "email", "header": "", "body": "It broke."},
        {"type": "comment", "author": "a.user", "header": "", "body": big},
    ])
    chunks = build_ticket_chunks(data, p)
    assert len(chunks) > 1
    assert all(c.metadata["ticket_id"] == "75100" for c in chunks)
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
    assert all(c.text.startswith("Ticket #75100") for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)  # unique ids


def test_has_images_flag_set(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "email", "header": "", "body": "See screenshot."},
        {"type": "comment", "author": "a.user", "header": "", "body": "Fixed per the image."},
    ], attachment_images=[{"mime": "image/png", "saved_path": "attachments/75100/c1.png"}])
    chunks = build_ticket_chunks(data, p)
    assert all(c.metadata["has_images"] is True for c in chunks)


from Dev.kb_chatbot.ticket_ingest import _parse_created_at


def test_parse_created_at_formats():
    assert _parse_created_at("2024-08-22 6:37 AM") == "2024-08-22"
    assert _parse_created_at("2024-08-22") == "2024-08-22"
    assert _parse_created_at("") == ""
    assert _parse_created_at("garbage") == ""


def test_chunk_has_recency_and_normalized_product(tmp_path):
    data, p = _ticket(tmp_path, [
        {"type": "email", "header": "", "body": "It broke."},
        {"type": "comment", "author": "a.user", "header": "", "body": "Fixed it."},
    ], product="FormFlow", created_at="2024-08-22 6:37 AM")
    chunks = build_ticket_chunks(data, p)
    m = chunks[0].metadata
    assert m["product"] == "formflow"       # normalized
    assert m["project"] == "FormFlow"      # raw kept
    assert m["created_at"] == "2024-08-22"
    assert "Date: 2024-08-22" in chunks[0].text
