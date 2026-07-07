"""Async ports of the sync Confluence page ops. Fake page; asserts call shape."""
import asyncio
from pathlib import Path

from scraper.kb_page_ops import capture_article, expand_macros

class _FakeLocator:
    def __init__(self, buttons): self._buttons = buttons
    async def all(self): return self._buttons

class _FakeButton:
    def __init__(self, fail=False): self.fail = fail; self.clicks = 0
    async def click(self, timeout=None):
        self.clicks += 1
        if self.fail: raise RuntimeError("not clickable")

class _FakePage:
    def __init__(self):
        self.gotos, self.shots, self.waits = [], [], 0
        self.buttons = [_FakeButton(), _FakeButton(fail=True)]
    async def goto(self, url, wait_until=None, timeout=None):
        self.gotos.append((url, wait_until))
    async def wait_for_timeout(self, ms): self.waits += 1
    def locator(self, sel): return _FakeLocator(self.buttons)
    async def screenshot(self, path=None, full_page=None): self.shots.append((path, full_page))
    async def content(self): return "<html>ok</html>"


def test_expand_macros_clicks_all_and_swallows_failures():
    page = _FakePage()
    asyncio.run(expand_macros(page))
    assert all(b.clicks >= 1 for b in page.buttons)       # failing button didn't abort


def test_capture_article_full_pipeline(tmp_path):
    page = _FakePage()
    html = asyncio.run(capture_article(page, "https://kb/x", tmp_path / "s" / "a.png"))
    assert html == "<html>ok</html>"
    assert page.gotos[0] == ("https://kb/x", "domcontentloaded")
    assert page.shots[0][1] is True                        # full_page screenshot
    assert (tmp_path / "s").exists()                       # parent dir created
