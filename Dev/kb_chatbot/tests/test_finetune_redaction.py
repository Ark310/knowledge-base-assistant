import sys, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune.redaction import find_leaks, scan_records, assert_clean, LeakError

def test_detects_real_email_and_phone_and_secret():
    assert "email" in find_leaks("contact john.doe@acme.com")
    assert "phone" in find_leaks("call +1 416 555 0134 today")
    assert "secret" in find_leaks("key YOUR_ANTHROPIC_API_KEY_HERE leaked")

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

def test_password_with_a_real_value_is_flagged():
    assert "password" in find_leaks("password: hunter2")

def test_redacted_password_placeholder_is_not_flagged():
    assert "password" not in find_leaks("Password: [redacted]")
