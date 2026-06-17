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


def test_allcaps_greeting_name_redacted():
    out = redact("HI Dana, please put it together", known_terms=[])
    assert "Dana" not in out


def test_multi_token_greeting_name_redacted():
    out = redact("Regards, Priya Patel", known_terms=[])
    assert "Priya" not in out and "Lee" not in out


def test_prose_names_after_action_verbs_redacted():
    assert "Riley" not in redact("Messaged Riley on Teams chat to check update", known_terms=[])
    assert "Priya" not in redact("I asked Priya to verify the fix", known_terms=[])
    assert "Robin" not in redact("asked the user (Robin) to perform UAT", known_terms=[])


def test_action_verb_keeps_technical_remainder():
    out = redact("Messaged Riley on Teams to restart the FixApp service", known_terms=[])
    assert "restart the FixApp service" in out


def test_real_tickets_no_obvious_names(tmp_path):
    import json
    from pathlib import Path
    for tid, leaked in [("75103", ["Riley"]), ("75111", ["Dana", "Robin"])]:
        p = Path(f"library/tickets/ticket_{tid}.json")
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        known = [data.get("organization",""), data.get("created_by",""), data.get("assignee","")]
        bodies = "\n".join(c.get("body","") for c in data.get("comments", []))
        out = redact(bodies, known_terms=[k for k in known if k])
        for name in leaked:
            assert name not in out, f"ticket {tid}: '{name}' leaked"


def test_greeting_does_not_eat_lowercase_words():
    out = redact("Thanks for the update on the FixApp restart", known_terms=[])
    assert "for the update" in out
    assert "FixApp restart" in out


def test_action_verb_does_not_eat_lowercase():
    out = redact("asked the team to restart the service", known_terms=[])
    # "team" is lowercase, not a Capitalized name -> must survive
    assert "team to restart the service" in out


def test_credential_values_redacted_keyword_kept():
    out = redact("Username: SandboxUser Password: 4hbR2$ltrop", known_terms=[])
    assert "4hbR2$ltrop" not in out
    assert "SandboxUser" not in out


def test_password_keyword_in_prose_survives():
    out = redact("Reset the password via Admin > Users then retry login", known_terms=[])
    assert "Reset the password via Admin" in out


def test_decrypt_and_api_key_values_redacted():
    out = redact("Decrypt key for above link: UnDjnih6Tbkc5yQSIBDW0J", known_terms=[])
    assert "UnDjnih6Tbkc5yQSIBDW0J" not in out
    out2 = redact("API Key: sk-abc123XYZ", known_terms=[])
    assert "sk-abc123XYZ" not in out2


def test_url_credential_pairs_redacted():
    out = redact("posted username=AppUser&password=9jL%23G%24s1 to the endpoint", known_terms=[])
    assert "AppUser" not in out
    assert "9jL" not in out


def test_at_mentions_redacted():
    out = redact("@Dana please provide the logs and @Hasan verify", known_terms=[])
    assert "Dana" not in out and "Hasan" not in out
    assert "please provide the logs" in out


def test_bare_domain_residue_redacted():
    out = redact("forwarded to sam@woodgrove.example for review", known_terms=[])
    assert "woodgrove.example" not in out
    assert "@woodgrove" not in out


def test_high_entropy_token_redacted():
    out = redact("ClientID: G5qjl8ujMGHJlfrNAnrPG0BM1sYohXIZAcobZ6vWm9LZAIT2", known_terms=[])
    assert "G5qjl8ujMGHJlfrNAnrPG0BM1sYohXIZAcobZ6vWm9LZAIT2" not in out
    assert "[redacted]" in out


def test_base64_blob_redacted():
    out = redact("file_bytes: VGVzdCBmaWxlIGZvciBwYXltZW50IHByb2Nlc3NpbmcgZGVtbw==", known_terms=[])
    assert "VGVzdCBmaWxlIGZvciBwYXltZW50IHByb2Nlc3NpbmcgZGVtbw" not in out


def test_jwt_redacted():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36"
    out = redact(f"token is {jwt}", known_terms=[])
    assert "eyJhbGciOiJIUzI1NiJ9" not in out


def test_hex_address_redacted():
    out = redact("wallet 0x52908400098527886E0F7030069857D2E4169EE7 confirmed", known_terms=[])
    assert "52908400098527886E0F7030069857D2E4169EE7" not in out


def test_version_string_not_over_redacted():
    out = redact("Upgrade to version 2.5.4.6 to fix this", known_terms=[])
    assert "2.5.4.6" in out


def test_ordinary_long_word_not_redacted():
    out = redact("This is an internationalization problem in the module", known_terms=[])
    assert "internationalization" in out


def test_short_id_not_redacted():
    out = redact("See order 75100 and ref AB12 for details", known_terms=[])
    assert "75100" in out and "AB12" in out


def test_clientid_label_redacted():
    out = redact("ClientID: G5qjl8ujMGHJ", known_terms=[])
    assert "G5qjl8ujMGHJ" not in out


def test_gateway_customer_id_redacted():
    out = redact("Gateway Customer ID: Comerica22964e769bbf2527", known_terms=[])
    assert "Comerica22964e769bbf2527" not in out


def test_multi_word_credential_value_redacted():
    out = redact("Password: my secret pass phrase", known_terms=[])
    assert "secret pass phrase" not in out
    assert "Password" in out  # the label survives


def test_credential_prose_without_separator_survives():
    out = redact("Please reset the password to continue", known_terms=[])
    assert "reset the password to continue" in out


def test_action_verb_multiword_name_fully_redacted():
    out = redact("I called Morgan Blake about the deal", known_terms=[])
    assert "Morgan" not in out and "Blake" not in out


def test_signature_line_after_signoff_dropped():
    out = redact("Resolved the issue.\nRegards,\nPriya Patel", known_terms=[])
    assert "Priya Patel" not in out


def test_non_signoff_short_capitalized_line_survives():
    out = redact("Open the panel.\nClick Save Now", known_terms=[])
    assert "Click Save Now" in out
