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
        """Navigate to the ticket edit page; poll until the title matches or a redirect occurs."""
        self.b.navigate(self.ticket_url(ticket_id))
        page = self.b._page
        for _ in range(24):
            if re.search(rf"^Ticket ID {re.escape(ticket_id)}\b", page.title()):
                break
            if f"/tickets/{ticket_id}/edit" not in page.url:  # redirected -> not found
                break
            time.sleep(0.5)
        return self.b.get_content()

    def open_subview(self, label: str) -> str:
        """Click the sidebar-menu-btn whose text starts with `label`; return the new HTML."""
        self.b._page.get_by_role("button").filter(
            has_text=re.compile(rf"^\s*{re.escape(label)}\b")).first.click()
        time.sleep(1.5)
        return self.b.get_content()

    def download_all(self, dest_dir: Path) -> list[Path]:
        """Click every Download button; save files to dest_dir; return saved paths."""
        dest_dir = Path(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        page = self.b._page
        for btn in page.get_by_role("button", name=re.compile(r"^\s*download\s*$", re.I)).all():
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
