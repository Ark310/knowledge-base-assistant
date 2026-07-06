def test_ticket_url():
    from scraper.portal.contoso_portal import AsyncContosoPortal
    p = AsyncContosoPortal(None, "https://support.contoso.example/")
    assert p.ticket_url("76511") == "https://support.contoso.example/edit_bug.aspx?id=76511"

def test_is_login_page():
    from scraper.portal.contoso_portal import AsyncContosoPortal
    p = AsyncContosoPortal(None, "https://support.contoso.example")
    assert p.is_login_page('<input id="user"><input id="pw">') is True
    assert p.is_login_page('<table>edit_bug fields</table>') is False


def test_download_all_retries_transient_failures(tmp_path):
    """First GET raises, retry succeeds -> file saved, nothing skipped (bug-146:
    213 one-shot download timeouts in a single v4.0.2 run)."""
    import asyncio
    from scraper.portal.contoso_portal import AsyncContosoPortal

    class FakeResponse:
        ok = True
        status = 200
        def __init__(self):
            self.headers = {}
        async def body(self):
            return b"data"

    class FakeRequest:
        def __init__(self):
            self.calls = 0
        async def get(self, url):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("simulated transient timeout")
            return FakeResponse()

    class FakeContext:
        def __init__(self):
            self.request = FakeRequest()

    class FakePage:
        def __init__(self, url):
            self.url = url
            self.context = FakeContext()

    base = "https://support.contoso.example"
    page = FakePage(f"{base}/edit_bug.aspx?id=76511")
    portal = AsyncContosoPortal(page, base)
    portal._last_html = '<a href="view_attachment.aspx?id=1">file.txt</a>'
    portal._active_subview = "files"

    saved = asyncio.run(portal.download_all(tmp_path))

    assert len(saved) == 1
    assert page.context.request.calls == 2   # one failure + one successful retry
