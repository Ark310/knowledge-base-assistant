import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.portal.tradedesk_portal import TradeDeskPortal

FIXTURES = Path(__file__).parent / "fixtures" / "tradedesk"


def test_ticket_url():
    portal = TradeDeskPortal(None, "https://portal.contoso.example/")
    assert portal.ticket_url("76511") == "https://portal.contoso.example/tickets/76511/edit"


def test_is_login_page_true_on_login_fixture():
    html = (FIXTURES / "login.html").read_text(encoding="utf-8")
    portal = TradeDeskPortal(None, "https://portal.contoso.example")
    assert portal.is_login_page(html) is True


def test_is_login_page_false_on_ticket_fixture():
    html = (FIXTURES / "ticket_detail.html").read_text(encoding="utf-8")
    portal = TradeDeskPortal(None, "https://portal.contoso.example")
    assert portal.is_login_page(html) is False
