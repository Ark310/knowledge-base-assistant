"""Single-run guard (v4.0.3, R7). One scrape at a time across ALL tabs — the
2026-07-02 collapse happened while tradedesk + Legacy batches overlapped in one
process. Module-level so every tab shares it."""
from __future__ import annotations
import threading

_lock = threading.Lock()
_owner: str | None = None


def acquire(owner: str) -> bool:
    global _owner
    with _lock:
        if _owner is None or _owner == owner:
            _owner = owner
            return True
        return False


def owner() -> str | None:
    return _owner


def release(owner: str) -> None:
    global _owner
    with _lock:
        if _owner == owner:
            _owner = None
