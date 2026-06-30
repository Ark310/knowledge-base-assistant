def test_ticket_url():
    from scraper.portal.contoso_portal import AsyncContosoPortal
    p = AsyncContosoPortal(None, "https://support.contoso.example/")
    assert p.ticket_url("76511") == "https://support.contoso.example/edit_bug.aspx?id=76511"

def test_is_login_page():
    from scraper.portal.contoso_portal import AsyncContosoPortal
    p = AsyncContosoPortal(None, "https://support.contoso.example")
    assert p.is_login_page('<input id="user"><input id="pw">') is True
    assert p.is_login_page('<table>edit_bug fields</table>') is False
