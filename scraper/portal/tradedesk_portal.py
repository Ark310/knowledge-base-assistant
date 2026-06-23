"""Authenticated-browser adapter for the portal.contoso.example SPA (v4).

Scrapes the RENDERED DOM — the API is end-to-end encrypted and is never touched.
Password is consumed by login() and never stored or logged.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from scraper.parsers.ticket_parser import is_not_found  # noqa: F401 (kept for callers)


class TradeDeskPortal:
    def __init__(self, browser, portal_url: str):
        self.b = browser
        self.base = portal_url.rstrip("/")

    # ------------------------------------------------------------------
    # Pure helpers (unit-testable without a browser)
    # ------------------------------------------------------------------

    def ticket_url(self, ticket_id: str) -> str:
        return f"{self.base}/tickets/{ticket_id}/edit"

    def is_login_page(self, html: str) -> bool:
        h = (html or "").lower()
        looks_login = ("sign in" in h) or ("/login" in h)
        return looks_login and "floating-dropdown-btn" not in h

    # ------------------------------------------------------------------
    # Browser-driving methods (covered by Phase 2 smoke test, not unit tests)
    # ------------------------------------------------------------------

    def login(self, username: str, password: str) -> bool:
        """Navigate to /login, fill credentials, click Sign In, return True on success.

        The password is never stored as an attribute or written to any log.
        """
        self.b.navigate(f"{self.base}/login")
        page = self.b._page
        page.get_by_role("textbox", name=re.compile("user", re.I)).fill(username)
        page.get_by_role("textbox", name=re.compile("pass", re.I)).fill(password)
        page.get_by_role("button", name=re.compile(r"^\s*sign in\s*$", re.I)).click()
        page.wait_for_load_state("domcontentloaded")
        time.sleep(2)
        return not self.is_login_page(self.b.get_content())

    def open_ticket(self, ticket_id: str) -> str:
        """Navigate to the ticket and return its rendered HTML once it is FULLY loaded.

        The SPA sets the title (and the sidebar sub-view counts the engine reads) only
        after it fetches+renders the ticket data. We wait for the field dropdowns AND the
        sidebar nav to exist — a fixed sleep / title-only wait races the async render and
        silently yields a half-rendered page whose "Resolve N"/"Files N" counts are absent,
        so the caller skips resolution and files.
        """
        self.b.navigate(self.ticket_url(ticket_id))
        page = self.b._page
        if f"/tickets/{ticket_id}/edit" not in page.url:   # redirected away -> not found
            return self.b.get_content()
        for sel in ("button.floating-dropdown-btn", "button.sidebar-menu-btn"):
            try:
                page.wait_for_selector(sel, timeout=20_000)
            except Exception:
                pass
        page.wait_for_timeout(500)   # small settle so the sidebar counts paint
        return self.b.get_content()

    def subview_count(self, label: str) -> int:
        """Count on a sidebar sub-view button (e.g. 'Resolve 1' -> 1), read from the
        RENDERED text. The HTML source wraps the digit in a child element, so a regex
        over page.content() misses it — read inner_text instead.
        """
        loc = self.b._page.locator(
            "button.sidebar-menu-btn",
            has_text=re.compile(rf"^\s*{re.escape(label)}\b", re.I),
        ).first
        try:
            txt = loc.inner_text(timeout=3_000)
        except Exception:
            return 0
        m = re.search(r"(\d+)", txt)
        return int(m.group(1)) if m else 0

    def _click_subview(self, label: str) -> bool:
        """Click the sidebar sub-view button whose text starts with `label`. False if absent."""
        btn = self.b._page.locator(
            "button.sidebar-menu-btn",
            has_text=re.compile(rf"^\s*{re.escape(label)}\b", re.I),
        ).first
        try:
            btn.click(timeout=5_000)
            return True
        except Exception:
            return False

    def open_subview(self, label: str, ready_selector: str | None = None) -> str:
        """Switch to a sub-view and return its rendered HTML.

        Clicks the PRECISE sidebar button (not a broad role match) and waits for the
        sub-view's own content to render (condition-based) rather than a fixed sleep.
        """
        if not self._click_subview(label):
            return self.b.get_content()
        page = self.b._page
        if ready_selector:
            try:
                page.wait_for_selector(ready_selector, timeout=15_000)
            except Exception:
                pass
        page.wait_for_timeout(500)
        return self.b.get_content()

    def download_all(self, dest_dir: Path) -> list[Path]:
        """Download every file in the Files panel; return the saved paths.

        Call this on the Files sub-view. The panel renders each file with an ICON
        button whose title contains "Download" (the portal wraps the value in literal
        quotes). We wait for those rows to render, then target them specifically — NOT
        the comment list's text "Download" buttons — so comment files are not
        double-downloaded. A per-file failure is skipped so one bad file can't abort the rest.
        """
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        page = self.b._page
        try:
            page.wait_for_selector('button[title*="Download"]', timeout=10_000)
        except Exception:
            return saved
        for btn in page.locator('button[title*="Download"]').all():
            try:
                with page.expect_download(timeout=30_000) as dl:
                    btn.click()
                d = dl.value
                target = dest_dir / d.suggested_filename
                d.save_as(str(target))
                saved.append(target)
            except Exception:
                continue
        return saved
