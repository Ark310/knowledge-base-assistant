# scraper/ticket_settings.py
"""Persisted ticket portal settings.

Portal URL and username are stored in state/ticket_settings.json.
Password is stored in the OS keyring (Windows Credential Manager) — never on disk.
If keyring is unavailable the password must be re-entered each session.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

_SERVICE = "ContosoKBScraper-TicketPortal"
log = logging.getLogger("scraper")


def _path() -> Path:
    from scraper.config import STATE_DIR
    return STATE_DIR / "ticket_settings.json"


def _kr():
    try:
        import keyring
        return keyring
    except Exception:
        return None


def keyring_available() -> bool:
    """True if keyring is importable and the OS backend responds."""
    kr = _kr()
    if not kr:
        return False
    try:
        kr.get_password(_SERVICE, "__probe__")
        return True
    except Exception:
        return False


def load() -> dict:
    """Return {"portal_url": ..., "username": ...}. Falls back to defaults."""
    try:
        p = _path()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"portal_url": "https://support.contoso.example", "username": ""}


def save(portal_url: str, username: str) -> None:
    """Persist portal URL and username (never the password)."""
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"portal_url": portal_url.strip(), "username": username.strip()}, indent=2),
        encoding="utf-8",
    )


def save_password(username: str, password: str) -> bool:
    """Store password in OS keyring. Returns True on success."""
    kr = _kr()
    if kr and username:
        try:
            kr.set_password(_SERVICE, username.strip(), password)
            return True
        except Exception as exc:
            log.warning("keyring save failed: %s", exc)
    return False


def load_password(username: str) -> str:
    """Return saved password from OS keyring, or '' if unavailable."""
    kr = _kr()
    if kr and username:
        try:
            return kr.get_password(_SERVICE, username.strip()) or ""
        except Exception as exc:
            log.warning("keyring load failed: %s", exc)
    return ""


def delete_password(username: str) -> None:
    kr = _kr()
    if kr and username:
        try:
            kr.delete_password(_SERVICE, username.strip())
        except Exception:
            pass
