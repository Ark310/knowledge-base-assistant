"""Async Chrome wrapper (system Chrome). One browser + one shared context;
each worker opens its own page (tab) in that context, so login is shared."""
from __future__ import annotations
from playwright.async_api import async_playwright

class AsyncBrowser:
    def __init__(self, headless: bool = False, timeout_ms: int = 30_000):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self.context = None

    async def open(self) -> "AsyncBrowser":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=self.headless, channel="chrome")
        # ignore_https_errors: the corporate portals' TLS chain is trusted by Chrome but
        # not by Playwright's Node fetch (APIRequestContext) — without this, attachment
        # downloads via context.request fail with "unable to get local issuer certificate"
        # (bug-101). Only cert ERRORS are ignored; valid certs are unaffected.
        self.context = await self._browser.new_context(
            accept_downloads=True, ignore_https_errors=True)
        self.context.set_default_timeout(self.timeout_ms)
        return self

    async def new_page(self):
        page = await self.context.new_page()
        page.set_default_timeout(self.timeout_ms)
        return page

    async def close(self):
        for closer in (
            lambda: self._browser.close() if self._browser else None,
            lambda: self._pw.stop() if self._pw else None,
        ):
            try:
                res = closer()
                if res is not None:
                    await res
            except Exception:
                pass
