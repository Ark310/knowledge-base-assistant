"""Async adapter for the legacy ASP.NET portal support.contoso.example. Page-bound.
Login #user/#pw; detail edit_bug.aspx; resolution Resolution.aspx (only when the
detail page shows 'resolution(filled)'). File attachments are `view_attachment.aspx`
links on the detail page — fetched via the authenticated request context (bug-101:
the old base64-inline assumption was stale; the live portal serves file URLs)."""
from __future__ import annotations
import logging
import re
from pathlib import Path
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from scraper.parsers.contoso_parser import is_not_found as _is_not_found

log = logging.getLogger("scraper")

_CT_EXT = {
    "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp",
    "application/pdf": "pdf", "text/plain": "txt", "text/html": "html",
    "application/zip": "zip", "application/octet-stream": "bin",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


def _looks_like_login(html: str) -> bool:
    h = (html or "").lower()
    return ('id="user"' in h) and ('id="pw"' in h)


async def contoso_login_once(browser, username: str, password: str) -> bool:
    """Log in once on the shared context (a throwaway page). Cookie shared by all tabs."""
    base = browser.base
    page = await browser.new_page()
    try:
        await page.goto(base, wait_until="domcontentloaded")
        if not _looks_like_login(await page.content()):
            return True                      # already authenticated (cookie)
        await page.fill("#user", username)
        await page.fill("#pw", password)
        await page.press("#pw", "Enter")     # ASP.NET form post
        await page.wait_for_load_state("domcontentloaded")
        await page.wait_for_timeout(1500)
        return not _looks_like_login(await page.content())
    finally:
        await page.close()


def _view_attachment_urls(html: str, base: str) -> list[tuple[str, str]]:
    """Unique (absolute_url, link_text) for every view_attachment.aspx anchor.

    Scans the WHOLE detail page — the live portal renders file links only at the
    top level (confirmed: 76511=4, 76091=8 matched the saved files exactly), so they
    map to top-level attachments. If a future ticket renders a view_attachment link
    INSIDE a comment body, scope this scan to exclude comment-row tables and attach
    it to that comment instead.
    """
    out, seen = [], set()
    for a in BeautifulSoup(html or "", "lxml").find_all("a", href=True):
        href = a["href"]
        if "view_attachment.aspx" not in href.lower():
            continue
        url = urljoin(base + "/", href)
        if url in seen:
            continue
        seen.add(url)
        out.append((url, " ".join((a.get_text() or "").split())))
    return out


def _unique_path(dest_dir: Path, name: str) -> Path:
    name = name or "attachment"
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
    """Run an async download op with small-backoff retries (bug-117: 213 one-shot
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


def _filename_for(resp, label: str, idx: int) -> str:
    """Prefer Content-Disposition filename, then the link text (if it has an ext),
    then attachment_<idx>.<ext-from-content-type>. (Never trust these for PII — they
    are filenames, but we do not log them.)"""
    cd = ""
    try:
        cd = resp.headers.get("content-disposition", "") or ""
    except Exception:
        cd = ""
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.I)
    if m:
        return m.group(1).strip().split("/")[-1].split("\\")[-1]
    if label and "." in label and len(label) <= 120:
        return label.strip().split("/")[-1].split("\\")[-1]
    ct = ""
    try:
        ct = (resp.headers.get("content-type", "") or "").split(";")[0].strip().lower()
    except Exception:
        ct = ""
    return f"attachment_{idx}.{_CT_EXT.get(ct, 'bin')}"


class AsyncContosoPortal:
    def __init__(self, page, base: str):
        self.page = page
        self.base = base.rstrip("/")
        self._last_html = ""
        self._active_subview = None   # 'resolve' | 'files' | None

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
        self._active_subview = None
        return self._last_html

    async def subview_count(self, label: str) -> int:
        h = (self._last_html or "")
        lab = label.lower()
        if lab.startswith("resolve"):
            return 1 if "resolution(filled)" in h.lower() else 0
        if lab.startswith("file"):
            return len(_view_attachment_urls(h, self.base))
        return 0

    async def open_subview(self, label: str, ready_selector: str | None = None) -> str:
        lab = label.lower()
        if lab.startswith("resolve"):
            self._active_subview = "resolve"
            m = re.search(r"[?&]id=(\d+)", self.page.url)
            tid = m.group(1) if m else ""
            await self.page.goto(f"{self.base}/Resolution.aspx?bugid={tid}",
                                 wait_until="domcontentloaded")
            await self.page.wait_for_timeout(600)
            return await self.page.content()
        # "Files": attachments are links already on the cached detail page — no nav.
        self._active_subview = "files"
        return self._last_html

    async def download_all(self, dest_dir: Path) -> list[Path]:
        # Only the Files context downloads. The Resolve view on this portal is text-only,
        # so when the engine calls download_all right after open_subview("Resolve") we
        # must NOT grab the detail-page attachments (they are top-level files, bug-101).
        if self._active_subview != "files":
            return []
        urls = _view_attachment_urls(self._last_html, self.base)
        if not urls:
            return []
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        log.info("download_all (contoso): %d view_attachment link(s) found", len(urls))
        for i, (url, label) in enumerate(urls):
            async def _one(url=url, label=label, i=i):
                resp = await self.page.context.request.get(url)
                if not resp.ok:
                    raise RuntimeError(f"http_{resp.status}")
                body = await resp.body()
                target = _unique_path(dest_dir, _filename_for(resp, label, i))
                target.write_bytes(body)
                return target
            try:
                saved.append(await _retry_download(_one))
            except Exception as exc:
                log.warning("download_all: attachment %d/%d failed after retries (%s)",
                            i + 1, len(urls), type(exc).__name__)
        log.info("download_all (contoso): %d attachment(s) saved", len(saved))
        return saved


def make_factory(base: str):
    return lambda page: AsyncContosoPortal(page, base)
