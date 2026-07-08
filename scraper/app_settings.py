# scraper/app_settings.py
"""Persisted app settings: per-type output folders (Tickets / Knowledge Base).
Defaults preserve the current locations so behavior is unchanged until the user edits them.
"""
from __future__ import annotations
import json
from pathlib import Path

def _file() -> Path:
    from scraper.config import STATE_DIR
    return Path(STATE_DIR) / "app_settings.json"

def _default_tickets() -> Path:
    from scraper.config import LIBRARY_BASE
    return Path(LIBRARY_BASE) / "tickets"

def _default_kb() -> Path:
    from scraper.config import LIBRARY_BASE
    return Path(LIBRARY_BASE) / "kb"

def load() -> dict:
    try:
        p = _file()
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

_VALID_MODES = ("light", "multi")

def save(tickets_dir: str, kb_dir: str, browser_mode: str | None = None) -> None:
    d = load()
    d["tickets_dir"] = str(tickets_dir)
    d["kb_dir"] = str(kb_dir)
    if browser_mode in _VALID_MODES:
        d["browser_mode"] = browser_mode
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")

def browser_mode() -> str:
    m = load().get("browser_mode")
    return m if m in _VALID_MODES else "light"

def set_browser_mode(mode: str) -> None:
    d = load()
    d["browser_mode"] = mode if mode in _VALID_MODES else "light"
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")

def headless() -> bool:
    """Run the scrape browser headless (no visible windows). Default False (headed).
    Headless is far lighter per tab — recommended for large batches (bug-111)."""
    return bool(load().get("headless", False))

def set_headless(on: bool) -> None:
    d = load()
    d["headless"] = bool(on)
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")

_VALID_PRIORITIES = ("low", "normal", "high")

def priority() -> str:
    """Process priority while scraping (v4.0.3). Default 'normal'."""
    v = load().get("priority")
    return v if v in _VALID_PRIORITIES else "normal"

def set_priority(level: str) -> None:
    d = load()
    d["priority"] = level if level in _VALID_PRIORITIES else "normal"
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, indent=2), encoding="utf-8")

def tickets_dir() -> Path:
    v = load().get("tickets_dir")
    return Path(v) if v else _default_tickets()

def kb_dir() -> Path:
    v = load().get("kb_dir")
    return Path(v) if v else _default_kb()
