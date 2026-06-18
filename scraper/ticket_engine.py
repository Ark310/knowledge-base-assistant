# scraper/ticket_engine.py
"""Ticket Portal scraper engine.

Drives a headed Chrome session to log into support.contoso.example,
navigate to each ticket, extract all fields, fetch the resolution page,
and persist JSON+MD to library/tickets/.

Credentials: URL + username from ticket_settings.json; password from OS keyring.
Password is NEVER written to disk or logged at any verbosity level.

Login form selectors confirmed from live portal inspection 2026-06-09:
  username: #user  (NOT #CTNM — that is the <form> element's id)
  password: #pw
  submit:   input[name='ctl01']
  session check: presence of id="user" AND id="pw" in HTML = login page.
"""
from __future__ import annotations

import json
import re
import threading
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from scraper.core import Browser, _is_browser_dead
from scraper.config import LIBRARY_BASE, STATE_DIR
from scraper.parsers.ticket_parser import is_not_found, parse_ticket_detail, parse_resolution
from scraper.writers.ticket_writer import save_ticket

log = logging.getLogger("scraper")

TICKETS_DIR = LIBRARY_BASE / "tickets"
TICKET_STATE_FILE = STATE_DIR / "scraped_tickets.json"

_SESSION_EXPIRED = object()   # sentinel


# ── Public types ──────────────────────────────────────────────────────────────

@dataclass
class TicketEngineCallbacks:
    on_log:      Callable[[str, str], None]  = field(default=lambda lvl, msg: None)
    on_progress: Callable[[int, int], None]  = field(default=lambda i, n: None)
    on_ticket:   Callable[[str, str], None]  = field(default=lambda tid, st: None)
    on_finished: Callable[[dict], None]      = field(default=lambda rep: None)


@dataclass
class CancellationToken:
    _cancelled: bool = False
    def cancel(self): self._cancelled = True
    @property
    def cancelled(self) -> bool: return self._cancelled


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


# ── Session detection ─────────────────────────────────────────────────────────

def _is_logged_out(html: str) -> bool:
    """True if the current page is the portal login screen.

    Confirmed via live Playwright inspection 2026-06-09:
    - Login page has exactly two visible inputs: id="user" (text) and id="pw" (password)
    - The form uses id="ctl00", NOT id="CTNM" (that was a different portal version)
    - On any authenticated page neither id="user" nor id="pw" appears
    """
    h = html.lower()
    return 'id="user"' in h and 'id="pw"' in h


# ── Login ─────────────────────────────────────────────────────────────────────

def _login(browser: Browser, base: str, username: str, password: str, cb) -> bool:
    """Navigate to portal root and log in. Returns True on success.

    Selectors confirmed from live portal DOM inspection:
      #user  — username text input
      #pw    — password input
      input[name='ctl01'] — submit button
    """
    try:
        browser.navigate(base)
        if not _is_logged_out(browser.get_content()):
            cb.on_log("info", "Portal session still active.")
            return True

        cb.on_log("info", "Logging into ticket portal...")
        browser.fill("#user", username)
        browser.fill("#pw", password)
        browser.click("input[name='ctl01']")
        browser.wait_for_load(timeout_ms=15_000)

        if _is_logged_out(browser.get_content()):
            cb.on_log("error", "Login failed — please check username and password.")
            return False

        cb.on_log("info", "Login successful.")
        return True
    except Exception as exc:
        cb.on_log("error", f"Login error: {exc}")
        return False


# ── Main engine ───────────────────────────────────────────────────────────────

def run_ticket_scrape(
    portal_url: str,
    username: str,
    password: str,
    ticket_ids: list[str],
    force: bool = False,
    cancel: CancellationToken | None = None,
    cb: TicketEngineCallbacks | None = None,
    workers: int = 1,
) -> dict:
    """Scrape the given ticket IDs. Returns summary report dict.

    workers: 1-4 parallel Chrome instances. Each opens its own browser and
             logs in independently. Progress is aggregated across all workers.
    The password is consumed here and never stored or logged.
    """
    if cb is None:
        cb = TicketEngineCallbacks()
    if cancel is None:
        cancel = CancellationToken()

    workers = max(1, min(4, workers))
    base = portal_url.rstrip("/")
    already_scraped = _load_scraped()
    total = len(ticket_ids)
    stats = {"total": total, "saved": 0, "skipped": 0, "not_found": 0, "failed": 0}

    TICKETS_DIR.mkdir(parents=True, exist_ok=True)

    # Locks: state_lock guards the scraped-tickets file (read-modify-write);
    #        stats_lock guards the stats dict and shared progress counter.
    state_lock    = threading.Lock()
    stats_lock    = threading.Lock()
    progress_ctr  = [0]   # mutable via list so the closure can increment it

    def worker_fn(chunk: list[str], worker_idx: int) -> None:
        prefix = f"[W{worker_idx + 1}] " if workers > 1 else ""
        browser = Browser(headless=False, timeout_ms=30_000)
        try:
            browser.open()
        except Exception as exc:
            cb.on_log("error", f"{prefix}Failed to launch browser: {exc}")
            return
        try:
            if not _login(browser, base, username, password, cb):
                cb.on_log("error", f"{prefix}Login failed; worker exiting.")
                return
            if workers > 1:
                cb.on_log("info", f"{prefix}Logged in — processing {len(chunk)} tickets.")

            for tid in chunk:
                if cancel.cancelled:
                    cb.on_log("warning", f"{prefix}Cancelled by user.")
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

                result = _fetch_ticket(browser, base, tid, cb)

                if result is _SESSION_EXPIRED:
                    cb.on_log("warning", f"{prefix}#{tid}: session expired — re-logging in...")
                    if not _login(browser, base, username, password, cb):
                        cb.on_log("error", f"{prefix}Re-login failed; worker aborting.")
                        break
                    result = _fetch_ticket(browser, base, tid, cb)

                if result is _SESSION_EXPIRED or result is None:
                    with stats_lock:
                        stats["failed"] += 1
                    cb.on_ticket(tid, "failed")
                elif result == "not_found":
                    with stats_lock:
                        stats["not_found"] += 1
                    cb.on_ticket(tid, "not_found")
                else:
                    save_ticket(result, TICKETS_DIR)
                    with state_lock:
                        _mark_scraped(tid)
                    with stats_lock:
                        stats["saved"] += 1
                    cb.on_ticket(tid, "ok")
                    title = result.get("title") or result.get("description", "")[:60]
                    cb.on_log("info", f"{prefix}[OK] #{tid}: {title}")

        finally:
            browser.close()

    if workers == 1:
        cb.on_log("info", f"--- Starting ticket scrape: {total} tickets ---")
        worker_fn(ticket_ids, 0)
    else:
        cb.on_log("info",
            f"--- Starting ticket scrape: {total} tickets ({workers} workers) ---")
        # Interleave IDs so workers pick up consecutive tickets in round-robin order,
        # giving balanced distribution even for short ranges.
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


def _fetch_ticket(browser: Browser, base: str, tid: str, cb) -> dict | str | None | object:
    """Fetch one ticket. Returns:
    - dict on success
    - "not_found" if the portal says the ticket doesn't exist
    - _SESSION_EXPIRED sentinel if we need to re-login
    - None on non-recoverable error
    """
    detail_url     = f"{base}/edit_bug.aspx?id={tid}"
    resolution_url = f"{base}/Resolution.aspx?bugid={tid}"

    for attempt in range(1, 4):
        try:
            browser.navigate(detail_url)
            html = browser.get_content()

            if _is_logged_out(html):
                return _SESSION_EXPIRED

            if is_not_found(html, tid):
                cb.on_log("info", f"[NOT FOUND] #{tid}")
                return "not_found"

            data = parse_ticket_detail(html, tid, base)
            if not data:
                cb.on_log("warning", f"#{tid}: parser returned empty — skipping.")
                return None

            # Resolution page — only fetched when the action bar shows "Resolution(filled)".
            # Confirmed 2026-06-09: <li id="resolution"> text is "Resolution(filled)"
            # when present, plain "Resolution" when not. Skipping saves one page load
            # per ticket that has no resolution.
            if "resolution(filled)" in html.lower():
                try:
                    browser.navigate(resolution_url)
                    res_html = browser.get_content()
                    resolution = parse_resolution(res_html)
                    if resolution:
                        data["resolution"] = resolution
                except Exception as res_exc:
                    cb.on_log("warning", f"#{tid}: resolution fetch error: {res_exc}")

            return data

        except Exception as exc:
            if _is_browser_dead(exc):
                cb.on_log("warning",
                    f"#{tid}: browser died — restarting (attempt {attempt}/3)...")
                try:
                    browser.restart()
                    cb.on_log("info", f"#{tid}: browser restarted.")
                except Exception as restart_exc:
                    cb.on_log("error", f"#{tid}: restart failed: {restart_exc}")
                    return None
            else:
                cb.on_log("warning", f"#{tid}: attempt {attempt}/3 failed: {exc}")
                if attempt == 3:
                    return None
                time.sleep(2 ** attempt)

    return None
