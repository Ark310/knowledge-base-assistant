from Dev.kb_chatbot.chat.ticket_redactor import redact


def test_emails_removed():
    out = redact("Contact sam.rivera@fabrikam.example please", known_terms=[])
    assert "@" not in out
    assert "sam.rivera" not in out


def test_phones_removed():
    out = redact("Call +44 (0)20 7350 5473 or 020 3992 9579", known_terms=[])
    assert "7350" not in out and "3992" not in out


def test_known_terms_removed_case_insensitive():
    out = redact("Issue reported by Fabrikam Financial via sam", known_terms=["Fabrikam Financial", "Sam"])
    assert "Fabrikam Financial" not in out
    assert "fabrikam financial" not in out.lower()
    assert "sam" not in out.lower()


def test_boilerplate_lines_dropped():
    txt = ("Subject: RE: ticket\n"
           "To: 'Contoso Support' <user@contoso.example>\n"
           "attachment: text.html view savesize: 26331 content-type: text/html\n"
           "FixApp session has been restarted")
    out = redact(txt, known_terms=[])
    assert "FixApp session has been restarted" in out
    assert "Subject:" not in out
    assert "attachment:" not in out


def test_real_sample_no_pii():
    import json
    from pathlib import Path
    base = Path("library/tickets/ticket_75100.json")
    data = json.loads(base.read_text(encoding="utf-8"))
    known = [data.get("organization",""), data.get("created_by",""), data.get("assignee","")]
    bodies = "\n".join(c.get("body","") for c in data.get("comments", []))
    out = redact(bodies, known_terms=[k for k in known if k])
    assert "@" not in out
    assert "Fabrikam Financial" not in out
    assert "fabrikam" not in out.lower()


def test_empty_input():
    assert redact("", known_terms=[]) == ""
    assert redact("   \n  ", known_terms=[]) == ""


def test_greeting_name_redacted_without_known_terms():
    out = redact("Hi Sam, FixApp session has been restarted Thanks", known_terms=[])
    assert "Sam" not in out
    assert "FixApp session has been restarted" in out   # technical content kept


def test_various_greetings_and_signoffs():
    assert "Bob" not in redact("Hello Bob, the issue is fixed", known_terms=[])
    assert "Sarah" not in redact("Dear Sarah, please retry", known_terms=[])
    assert "Mike" not in redact("Thanks Mike", known_terms=[])
    assert "Jane" not in redact("Regards, Jane", known_terms=[])


def test_greeting_keeps_following_sentence():
    out = redact("Hi Sam, the FixApp was restarted and prices resumed", known_terms=[])
    assert "FixApp was restarted" in out
    assert "prices resumed" in out
