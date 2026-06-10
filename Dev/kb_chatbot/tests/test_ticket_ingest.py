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
    assert c.metadata["url"] == data["resolution_url"]
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
    assert "@" not in c.text
    assert "Fabrikam Financial" not in c.text
    assert "fabrikam" not in c.text.lower()
    assert "Sam" not in c.text


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
            org = data.get("organization", "")
            if org:
                assert org not in c.text, f"{tid}: org '{org}' leaked"
