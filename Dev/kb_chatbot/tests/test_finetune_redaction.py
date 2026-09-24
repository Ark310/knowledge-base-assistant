import sys, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune.redaction import find_leaks, scan_records, assert_clean, LeakError

def test_detects_real_email_and_phone_and_secret():
    assert "email" in find_leaks("contact john.doe@acme.com")
    assert "phone" in find_leaks("call +1 416 555 0134 today")
    fake_key = "sk-" + "ant-" + "a1B2c3D4e5F6g7H8i9J0"  # built at runtime: synthetic, not a real key
    assert "secret" in find_leaks(f"key {fake_key} leaked")

def test_ignores_redacted_placeholders_and_iso_dates():
    assert find_leaks("emailed [redacted] on 2024-08-22 re ticket #54000") == []

def test_assert_clean_raises_on_planted_pii():
    recs = [{"messages":[{"role":"user","content":"ok"},
                         {"role":"assistant","content":"mail jane@acme.com"}]}]
    with pytest.raises(LeakError):
        assert_clean(recs)

def test_assert_clean_passes_when_clean():
    recs = [{"messages":[{"role":"assistant","content":"do Y. Sources: [Ticket #1](u)"}]}]
    assert_clean(recs)  # no raise


def test_scrub_neutralizes_pii():
    from Dev.kb_chatbot.finetune.redaction import scrub
    out = scrub("mail bob@acme.com or call 416-555-0134")
    assert "bob@acme.com" not in out
    assert "416-555-0134" not in out
    assert "[redacted]" in out


def test_scrub_records_cleans_message_content():
    from Dev.kb_chatbot.finetune.redaction import scrub_records, scan_records
    recs = [{"messages":[{"role":"user","content":"reach jane@acme.com"}]}]
    scrub_records(recs)
    assert scan_records(recs) == []  # nothing PII-shaped remains after scrub

def test_password_with_a_real_value_is_flagged():
    assert "password" in find_leaks("password: hunter2")

def test_redacted_password_placeholder_is_not_flagged():
    assert "password" not in find_leaks("Password: [redacted]")

def test_detects_standard_10_digit_phone_formats():
    assert "phone" in find_leaks("call 416-555-0134")
    assert "phone" in find_leaks("reach us at (416) 555-0134")
    assert "phone" in find_leaks("fax 416.555.0134")

def test_does_not_flag_iso_date_or_ticket_id_as_phone():
    assert "phone" not in find_leaks("released on 2024-08-22 for ticket #54000")
