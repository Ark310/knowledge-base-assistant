import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.portal.tradedesk_portal import TradeDeskPortal, _unique_path

FIXTURES = Path(__file__).parent / "fixtures" / "tradedesk"


def test_unique_path_no_collision(tmp_path):
    assert _unique_path(tmp_path, "text.html") == tmp_path / "text.html"


def test_unique_path_dedupes_collisions(tmp_path):
    # Two different files served with the same name must not overwrite each other.
    (tmp_path / "text.html").write_text("first")
    p2 = _unique_path(tmp_path, "text.html")
    assert p2 == tmp_path / "text_1.html"
    p2.write_text("second")
    p3 = _unique_path(tmp_path, "text.html")
    assert p3 == tmp_path / "text_2.html"


def test_unique_path_no_extension(tmp_path):
    (tmp_path / "README").write_text("x")
    assert _unique_path(tmp_path, "README") == tmp_path / "README_1"


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
