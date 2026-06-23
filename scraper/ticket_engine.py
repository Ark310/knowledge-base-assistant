"""Ticket Portal scraper engine.

Drives a headed Chrome session through TradeDeskPortal to log into
portal.contoso.example, navigate to each ticket, extract all fields, fetch the
Resolve and Files sub-views, download every file through the browser, and
persist JSON+MD to the output directory.

Password is consumed by portal.login() and is NEVER stored, logged, or
passed to any shell command.
"""
from __future__ import annotations

import json
import re
import threading
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from scraper.config import LIBRARY_BASE, STATE_DIR
from scraper.control import RunControl
from scraper.parsers.ticket_parser import is_not_found, parse_ticket_detail, parse_resolution
from scraper.writers.ticket_writer import save_ticket

log = logging.getLogger("scraper")

TICKETS_DIR = LIBRARY_BASE / "tickets"
TICKET_STATE_FILE = STATE_DIR / "scraped_tickets.json"

CancellationToken = RunControl  # back-compat for the (Phase-4) GUI import

_SESSION_EXPIRED = object()   # sentinel


# ── Public types ──────────────────────────────────────────────────────────────

@dataclass
class TicketEngineCallbacks:
    on_log:         Callable[[str, str], None]        = field(default=lambda lvl, msg: None)
    on_progress:    Callable[[int, int], None]        = field(default=lambda i, n: None)
    on_ticket:      Callable[[str, str], None]        = field(default=lambda tid, st: None)
    on_finished:    Callable[[dict], None]            = field(default=lambda rep: None)
    on_ticket_meta: Callable[[str, str, int], None]   = field(default=lambda tid, title, nf: None)


# ── Ticket ID parsing ─────────────────────────────────────────────────────────

def parse_ticket_input(raw: str) -> list[str]:
    """Parse free-form ticket input into a deduplicated ordered list of IDs.

    Accepts: single ID, comma-separated list, N-M ranges (inclusive).
    Example: "74500, 74510-74515, 74520" → ["74500","74510",...,"74515","74520"]
    """
    ids: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[,\s]+", raw.strip()):
        token = token.strip()
        if not token:
            continue
        m = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", token)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo > hi:
                lo, hi = hi, lo
            for n in range(lo, hi + 1):
                tid = str(n)
                if tid not in seen:
                    ids.append(tid); seen.add(tid)
        elif re.fullmatch(r"\d+", token):
            if token not in seen:
                ids.append(token); seen.add(token)
    return ids


# ── State tracking ────────────────────────────────────────────────────────────

def _load_scraped() -> set[str]:
    if TICKET_STATE_FILE.exists():
        try:
            return set(json.loads(TICKET_STATE_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def _mark_scraped(tid: str) -> None:
    TICKET_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    scraped = _load_scraped()
    scraped.add(tid)
    TICKET_STATE_FILE.write_text(json.dumps(sorted(scraped), indent=2), encoding="utf-8")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clamp_workers(n: int) -> int:
    return max(1, min(10, int(n or 1)))


def _default_portal_factory(portal_url: str):
    from scraper.core import Browser
    from scraper.portal.tradedesk_portal import TradeDeskPortal
    b = Browser(headless=False, timeout_ms=30_000)
    b.open()
    return TradeDeskPortal(b, portal_url)


def _match_paths(items, by_name: dict) -> None:
    """Annotate attachment dicts with saved_path where a downloaded file matches by label."""
    for a in items or []:
        p = by_name.get(a.get("label"))
        if p:
            a["saved_path"] = str(p)


def _fetch_ticket(portal, tid: str, output_dir: Path, cb) -> dict | str | None | object:
    """Fetch one ticket via the portal adapter.

    Returns:
      - dict on success
      - "not_found" if the portal redirected away (ticket does not exist)
      - _SESSION_EXPIRED if the page looks like the login screen
      - None on non-recoverable parse failure
    """
    html = portal.open_ticket(tid)

    if portal.is_login_page(html):
        return _SESSION_EXPIRED

    if is_not_found(html, tid):
        cb.on_log("info", f"[NOT FOUND] #{tid}")
        return "not_found"

    data = parse_ticket_detail(html, tid, portal.base)
    if not data:
        cb.on_log("warning", f"#{tid}: parser returned empty — skipping.")
        return None

    # Read sub-view counts from the RENDERED sidebar (not a regex over HTML source —
    # the portal wraps the count digit in a child element, so source regex reads 0).
    resolve_n = portal.subview_count("Resolve")
    files_n = portal.subview_count("Files")
    cb.on_log("info", f"#{tid}: sub-views detected — Resolve={resolve_n}, Files={files_n}")

    # Resolution sub-view — fetched when the sidebar shows "Resolve N>0"
    if resolve_n > 0:
        res = parse_resolution(portal.open_subview("Resolve", ready_selector="div.resolution-container"))
        data["resolution"] = res
        cb.on_log("info",
            f"#{tid}: resolution {len(res.get('text', ''))} chars, "
            f"{len(res.get('attachments') or [])} file ref(s)")

    # Files sub-view — download all attachments when "Files N>0"
    saved: list[Path] = []
    if files_n > 0:
        portal.open_subview("Files", ready_selector='button[title*="Download"]')
        saved = portal.download_all(Path(output_dir) / "attachments" / tid)
        cb.on_log("info", f"#{tid}: downloaded {len(saved)} file(s)")

    data["attachments"] = [{"filename": p.name, "saved_path": str(p)} for p in saved]

    # Annotate comment and resolution attachment dicts with saved_path
    by_name = {p.name: p for p in saved}
    for c in data.get("comments") or []:
        _match_paths(c.get("attachments"), by_name)
    if isinstance(data.get("resolution"), dict):
        _match_paths(data["resolution"].get("attachments"), by_name)

    return data


# ── Main engine ───────────────────────────────────────────────────────────────

def run_ticket_scrape(
    portal_url: str,
    username: str,
    password: str,
    ticket_ids: list[str],
    force: bool = False,
    control: RunControl | None = None,
    cb: TicketEngineCallbacks | None = None,
    workers: int = 1,
    output_dir=None,
    portal_factory=None,
    cancel: RunControl | None = None,  # legacy kwarg, back-compat
) -> dict:
    """Scrape the given ticket IDs through TradeDeskPortal. Returns a summary dict.

    workers: 1–10 parallel portal instances (clamped). Each opens its own
             browser and logs in independently. Progress is aggregated.
    The password is consumed here and is never stored or logged.
    """
    control = control or cancel or RunControl()
    if cb is None:
        cb = TicketEngineCallbacks()
    if portal_factory is None:
        portal_factory = _default_portal_factory

    workers = _clamp_workers(workers)
    output_dir = Path(output_dir) if output_dir else TICKETS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    already_scraped = _load_scraped()
    total = len(ticket_ids)
    stats = {"total": total, "saved": 0, "skipped": 0, "not_found": 0, "failed": 0}

    state_lock = threading.Lock()   # protects the scraped-tickets file
    stats_lock = threading.Lock()   # protects stats dict + progress counter
    progress_ctr = [0]

    def worker_fn(chunk: list[str], worker_idx: int) -> None:
        prefix = f"[W{worker_idx + 1}] " if workers > 1 else ""
        portal = portal_factory(portal_url)
        try:
            if not portal.login(username, password):
                cb.on_log("error", f"{prefix}Login failed; worker exiting.")
                return
            if workers > 1:
                cb.on_log("info", f"{prefix}Logged in — processing {len(chunk)} tickets.")

            for tid in chunk:
                control.wait_if_paused()
                if control.cancelled:
                    cb.on_log("warning", f"{prefix}Cancelled.")
                    break

                with stats_lock:
                    progress_ctr[0] += 1
                    cb.on_progress(progress_ctr[0], total)

                if not force and tid in already_scraped:
                    cb.on_log("info", f"{prefix}[SKIP] #{tid} already scraped.")
                    cb.on_ticket(tid, "skipped")
                    with stats_lock:
                        stats["skipped"] += 1
                    continue

                result = _fetch_ticket(portal, tid, output_dir, cb)

                # Re-login once on session expiry
                if result is _SESSION_EXPIRED:
                    cb.on_log("warning", f"{prefix}#{tid}: session expired — re-logging in...")
                    if not portal.login(username, password):
                        cb.on_log("error", f"{prefix}Re-login failed; worker aborting.")
                        break
                    result = _fetch_ticket(portal, tid, output_dir, cb)

                if result is _SESSION_EXPIRED or result is None:
                    with stats_lock:
                        stats["failed"] += 1
                    cb.on_ticket(tid, "failed")
                elif result == "not_found":
                    with stats_lock:
                        stats["not_found"] += 1
                    cb.on_ticket(tid, "not_found")
                else:
                    save_ticket(result, output_dir)
                    with state_lock:
                        _mark_scraped(tid)
                        already_scraped.add(tid)  # keep in-process set current
                    with stats_lock:
                        stats["saved"] += 1
                    cb.on_ticket(tid, "ok")
                    cb.on_ticket_meta(
                        tid,
                        result.get("title", ""),
                        len(result.get("attachments") or []),
                    )
                    title = result.get("title") or ""
                    cb.on_log("info", f"{prefix}[OK] #{tid}: {title}")

        finally:
            portal.b.close()  # portal.b is the Browser instance (TradeDeskPortal contract)

    cb.on_log("info",
        f"--- Starting ticket scrape: {total} tickets"
        + (f" ({workers} workers)" if workers > 1 else "") + " ---")

    if workers == 1:
        worker_fn(ticket_ids, 0)
    else:
        # Round-robin interleave for balanced distribution
        chunks = [ticket_ids[i::workers] for i in range(workers)]
        threads = [
            threading.Thread(target=worker_fn, args=(chunk, i), daemon=True)
            for i, chunk in enumerate(chunks)
            if chunk
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    cb.on_finished(stats)
    return stats
