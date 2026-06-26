"""Canonical ticket schema + async portal contract shared by both portals."""
from __future__ import annotations
from typing import Protocol, runtime_checkable
from pathlib import Path

TICKET_SCHEMA_KEYS = ("id", "title", "url", "fields", "comments", "resolution", "attachments")

def empty_ticket(ticket_id: str, url: str = "") -> dict:
    """A canonical ticket dict with every key present (the shape both portals emit)."""
    return {
        "id": ticket_id, "title": "", "url": url, "fields": {},
        "comments": [],   # [{author,date,body,images:[{mime,saved_path}],attachments:[{label,saved_path}]}]
        "resolution": {"text": "", "comments": [], "attachments": []},
        "attachments": [],  # [{filename, saved_path}]
    }

def looks_like_login(html: str) -> bool:
    """True when the page looks like the login screen AND no ticket fields are present."""
    h = (html or "").lower()
    return (("sign in" in h) or ("/login" in h)) and "floating-dropdown-btn" not in h

@runtime_checkable
class AsyncPortal(Protocol):
    base: str
    def ticket_url(self, ticket_id: str) -> str: ...
    def is_login_page(self, html: str) -> bool: ...
    def is_not_found(self, html: str, ticket_id: str) -> bool: ...
    async def login(self, username: str, password: str) -> bool: ...
    async def open_ticket(self, ticket_id: str) -> str: ...
    async def subview_count(self, label: str) -> int: ...
    async def open_subview(self, label: str, ready_selector: str | None = None) -> str: ...
    async def download_all(self, dest_dir: Path) -> list[Path]: ...
