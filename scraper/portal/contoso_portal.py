"""Async adapter for the legacy ASP.NET portal support.contoso.example. Page-bound.
Login #user/#pw; detail edit_bug.aspx; resolution Resolution.aspx (only when the
detail page shows 'resolution(filled)'). Legacy embeds images inline as base64
(handled by the parser + writer), so there is no Files sub-view / download_all."""
from __future__ import annotations
import logging
from pathlib import Path
from scraper.parsers.contoso_parser import is_not_found as _is_not_found

log = logging.getLogger("scraper")

def _looks_like_login(html: str) -> bool:
    h = (html or "").lower()
    return ('id="user"' in h) and ('id="pw"' in h)

async def contoso_login_once(browser, username: str, password: str) -> bool:
    base = browser.base
    page = await browser.new_page()
    try:
        await page.goto(base, wait_until="domcontentloaded")
        html = await page.content()
        if not _looks_like_login(html):
            return True                      # already authenticated (cookie)
        await page.fill("#user", username)
        await page.fill("#pw", password)
        # submit: press Enter in the password field (ASP.NET form post)
        await page.press("#pw", "Enter")
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1500)
        return not _looks_like_login(await page.content())
    finally:
        await page.close()

class AsyncContosoPortal:
    def __init__(self, page, base: str):
        self.page = page
        self.base = base.rstrip("/")
        self._last_html = ""
    def ticket_url(self, tid: str) -> str:
        return f"{self.base}/edit_bug.aspx?id={tid}"
    def is_login_page(self, html: str) -> bool:
        return _looks_like_login(html)
    def is_not_found(self, html: str, tid: str) -> bool:
        return _is_not_found(html, tid)
    async def login(self, username, password) -> bool:   # multi-window mode per-worker login
        return True
    async def open_ticket(self, tid: str) -> str:
        await self.page.goto(self.ticket_url(tid), wait_until="domcontentloaded")
        await self.page.wait_for_timeout(800)
        self._last_html = await self.page.content()
        return self._last_html
    async def subview_count(self, label: str) -> int:
        # Resolve = 1 iff the detail page action bar shows 'resolution(filled)'. No Files sub-view.
        if label.lower().startswith("resolve"):
            return 1 if "resolution(filled)" in (self._last_html or "").lower() else 0
        return 0
    async def open_subview(self, label: str, ready_selector: str | None = None) -> str:
        if not label.lower().startswith("resolve"):
            return ""
        # tid is embedded in the current detail URL (edit_bug.aspx?id=NN)
        import re
        m = re.search(r"[?&]id=(\d+)", self.page.url)
        tid = m.group(1) if m else ""
        await self.page.goto(f"{self.base}/Resolution.aspx?bugid={tid}", wait_until="domcontentloaded")
        await self.page.wait_for_timeout(600)
        return await self.page.content()
    async def download_all(self, dest_dir: Path) -> list[Path]:
        return []   # legacy uses inline base64 images (parser+writer); confirm in Task 5

def make_factory(base: str):
    return lambda page: AsyncContosoPortal(page, base)
