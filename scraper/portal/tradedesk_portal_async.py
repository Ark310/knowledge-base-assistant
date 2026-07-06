"""Async adapter for portal.contoso.example SPA. Page-bound (one page per worker tab).
Selectors/timing identical to the sync TradeDeskPortal; login happens once per context."""
from __future__ import annotations
import logging
import re
from pathlib import Path
from scraper.parsers.ticket_parser import is_not_found as _is_not_found
from scraper.portal.base_portal import looks_like_login

log = logging.getLogger("scraper")

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

async def _retry_download(fn, attempts: int = 2, base_delay: float = 0.5):
    """Run an async download op with small-backoff retries (bug-146: 213 one-shot
    download timeouts in a single v4.0.2 run). Raises the last error."""
    import asyncio
    last = None
    for i in range(attempts + 1):
        try:
            return await fn()
        except Exception as exc:
            last = exc
            if i < attempts:
                await asyncio.sleep(base_delay * (2 ** i))
    raise last

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
        """Fast-path readiness: poll every 250ms for EITHER the fields rendering
        (found) OR the SPA redirecting away (not-found -> /bugs). v4.0.2 burned a
        fixed 1.5s + up to 2×20s selector waits per ticket; 7,485 not-founds in
        one run paid full price (bug-146)."""
        await self.page.goto(self.ticket_url(tid), wait_until="domcontentloaded")
        edit_path = f"/tickets/{tid}/edit"
        ready = False
        for _ in range(48):                     # ≤ ~12s in 250ms steps
            if edit_path not in self.page.url:
                return await self.page.content()          # redirected: not found
            try:
                if await self.page.locator("button.floating-dropdown-btn").count():
                    ready = True
                    break
            except Exception:
                pass
            await self.page.wait_for_timeout(250)
        if ready:
            try:
                await self.page.wait_for_selector("button.sidebar-menu-btn", timeout=8_000)
            except Exception:
                pass
            await self.page.wait_for_timeout(300)
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
        try:   # diagnostic (counts only, no PII): what does this sub-view expose?
            dl = await self.page.locator('button[title*="Download"]').count()
            cc = await self.page.locator('div.comment-html-content').count()
            rc = await self.page.locator('div.resolution-container').count()
            log.info("open_subview(%s): %d download-btn, %d comment-block, %d resolution-container",
                     label, dl, cc, rc)
        except Exception:
            pass
        return await self.page.content()
    async def download_all(self, dest_dir: Path) -> list[Path]:
        dest_dir = Path(dest_dir); dest_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        try:
            await self.page.wait_for_selector('button[title*="Download"]', timeout=10_000)
        except Exception:
            log.info("download_all: no Download button rendered in time")
            return saved
        btns = await self.page.locator('button[title*="Download"]').all()
        log.info("download_all: %d Download button(s) found", len(btns))
        skipped = 0
        for i, btn in enumerate(btns):
            async def _one(btn=btn):
                async with self.page.expect_download(timeout=30_000) as dl:
                    await btn.click()
                d = await dl.value
                target = _unique_path(dest_dir, d.suggested_filename)
                await d.save_as(str(target))
                return target
            try:
                saved.append(await _retry_download(_one))
            except Exception as exc:
                skipped += 1
                # filename omitted — may carry PII; log index + error type only
                log.warning("download_all: button %d/%d failed after retries (%s)",
                            i + 1, len(btns), type(exc).__name__)
        if skipped:
            log.warning("download_all: %d of %d download(s) skipped", skipped, len(btns))
        return saved

def make_factory(base: str):
    """Returns page->AsyncTradeDeskPortal for the engine's page_portal_factory."""
    return lambda page: AsyncTradeDeskPortal(page, base)
