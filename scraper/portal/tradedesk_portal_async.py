"""Async adapter for portal.contoso.example SPA. Page-bound (one page per worker tab).
Selectors/timing identical to the sync TradeDeskPortal; login happens once per context."""
from __future__ import annotations
import re
from pathlib import Path
from scraper.parsers.ticket_parser import is_not_found as _is_not_found
from scraper.portal.base_portal import looks_like_login

def _unique_path(dest_dir: Path, name: str) -> Path:
    name = name or "file"
    target = dest_dir / name
    if not target.exists():
        return target
    stem, dot, ext = name.rpartition(".")
    base, suffix = (stem, f".{ext}") if dot else (name, "")
    i = 1
    while (cand := dest_dir / f"{base}_{i}{suffix}").exists():
        i += 1
    return cand

async def tradedesk_login_once(browser, username: str, password: str) -> bool:
    """Log in once on the shared context (a throwaway page); cookie shared by all tabs."""
    base = browser.base  # set by make_factory wiring below
    page = await browser.new_page()
    try:
        await page.goto(f"{base}/login", wait_until="domcontentloaded")
        await page.get_by_role("textbox", name=re.compile("user", re.I)).fill(username)
        await page.get_by_role("textbox", name=re.compile("pass", re.I)).fill(password)
        await page.get_by_role("button", name=re.compile(r"^\s*sign in\s*$", re.I)).click()
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(2_000)
        html = await page.content()
        return not looks_like_login(html)
    finally:
        await page.close()

class AsyncTradeDeskPortal:
    def __init__(self, page, base: str):
        self.page = page
        self.base = base.rstrip("/")
    def ticket_url(self, tid: str) -> str:
        return f"{self.base}/tickets/{tid}/edit"
    def is_login_page(self, html: str) -> bool:
        return looks_like_login(html)
    def is_not_found(self, html: str, tid: str) -> bool:
        return _is_not_found(html, tid)
    async def login(self, username, password) -> bool:   # multi-window mode (Phase 2) uses this
        return True
    async def open_ticket(self, tid: str) -> str:
        await self.page.goto(self.ticket_url(tid), wait_until="domcontentloaded")
        await self.page.wait_for_timeout(1_500)
        if f"/tickets/{tid}/edit" not in self.page.url:
            return await self.page.content()
        for sel in ("button.floating-dropdown-btn", "button.sidebar-menu-btn"):
            try:
                await self.page.wait_for_selector(sel, timeout=20_000)
            except Exception:
                pass
        await self.page.wait_for_timeout(500)
        return await self.page.content()
    async def subview_count(self, label: str) -> int:
        loc = self.page.locator("button.sidebar-menu-btn",
            has_text=re.compile(rf"^\s*{re.escape(label)}\b", re.I)).first
        try:
            txt = await loc.inner_text(timeout=3_000)
        except Exception:
            return 0
        m = re.search(r"(\d+)", txt)
        return int(m.group(1)) if m else 0
    async def _click_subview(self, label: str) -> bool:
        btn = self.page.locator("button.sidebar-menu-btn",
            has_text=re.compile(rf"^\s*{re.escape(label)}\b", re.I)).first
        try:
            await btn.click(timeout=5_000); return True
        except Exception:
            return False
    async def open_subview(self, label: str, ready_selector: str | None = None) -> str:
        if not await self._click_subview(label):
            return await self.page.content()
        if ready_selector:
            try:
                await self.page.wait_for_selector(ready_selector, timeout=15_000)
            except Exception:
                pass
        await self.page.wait_for_timeout(500)
        return await self.page.content()
    async def download_all(self, dest_dir: Path) -> list[Path]:
        dest_dir = Path(dest_dir); dest_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        try:
            await self.page.wait_for_selector('button[title*="Download"]', timeout=10_000)
        except Exception:
            return saved
        for btn in await self.page.locator('button[title*="Download"]').all():
            try:
                async with self.page.expect_download(timeout=30_000) as dl:
                    await btn.click()
                d = await dl.value
                target = _unique_path(dest_dir, d.suggested_filename)
                await d.save_as(str(target))
                saved.append(target)
            except Exception:
                continue
        return saved

def make_factory(base: str):
    """Returns page->AsyncTradeDeskPortal for the engine's page_portal_factory."""
    return lambda page: AsyncTradeDeskPortal(page, base)
