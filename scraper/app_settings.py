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

def save(tickets_dir: str, kb_dir: str) -> None:
    p = _file()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"tickets_dir": str(tickets_dir), "kb_dir": str(kb_dir)}, indent=2),
                 encoding="utf-8")

def tickets_dir() -> Path:
    v = load().get("tickets_dir")
    return Path(v) if v else _default_tickets()

def kb_dir() -> Path:
    v = load().get("kb_dir")
    return Path(v) if v else _default_kb()
