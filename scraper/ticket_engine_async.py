"""Async ticket engine — light mode (1 browser, 1 login, N tabs). Crash-resilient:
shared asyncio.Queue, bounded redispatch, in-place page rebuild, drain-to-failed,
exactly-once terminal status. Logs exception TYPE only (no PII)."""
from __future__ import annotations
import asyncio
from pathlib import Path

from scraper.ticket_engine import (
    MAX_TICKET_ATTEMPTS, MAX_WORKER_REBUILDS, TicketEngineCallbacks,
    _load_scraped, _mark_scraped, _match_paths, TICKETS_DIR,
)
from scraper.parsers.ticket_parser import parse_ticket_detail, parse_resolution
from scraper.writers.ticket_writer import save_ticket

_SESSION_EXPIRED = object()
# When a run ends with many tickets still pending (pool collapse / login failure /
# cancel), we mark them all failed but emit at most this many per-ticket GUI updates —
# a full per-item emit floods the Qt signal queue and hangs the UI on large batches
# (bug-111: an 18k run drained ~17k tickets one-by-one and froze the app).
_DRAIN_TICKET_CAP = 200

async def _fetch_ticket(portal, tid, output_dir, cb, parse_fn, parse_resolution_fn) -> dict | str | object | None:
    html = await portal.open_ticket(tid)
    if portal.is_login_page(html):
        return _SESSION_EXPIRED
    if portal.is_not_found(html, tid):
        cb.on_log("info", f"[NOT FOUND] #{tid}")
        return "not_found"
    data = parse_fn(html, tid, portal.base)
    if not data:
        cb.on_log("warning", f"#{tid}: parser returned empty — skipping.")
        return None
    resolve_n = await portal.subview_count("Resolve")
    files_n = await portal.subview_count("Files")
    cb.on_log("info", f"#{tid}: sub-views — Resolve={resolve_n}, Files={files_n}")
    res_saved: list[Path] = []
    if resolve_n > 0:
        res_html = await portal.open_subview("Resolve", ready_selector="div.resolution-container")
        data["resolution"] = parse_resolution_fn(res_html)
        # The Resolve view has its OWN Download button(s); the Files panel does NOT
        # include the resolution's file, so download it here while the view is open.
        res_saved = await portal.download_all(Path(output_dir) / "attachments" / tid)
        _res = data["resolution"]
        cb.on_log("info",
            f"#{tid}: resolution {len(_res.get('text') or '')} chars, "
            f"{len(_res.get('comments') or [])} comment(s), {len(res_saved)} file(s)")
    files_saved: list[Path] = []
    if files_n > 0:
        await portal.open_subview("Files", ready_selector='button[title*="Download"]')
        files_saved = await portal.download_all(Path(output_dir) / "attachments" / tid)
        cb.on_log("info", f"#{tid}: downloaded {len(files_saved)} file(s)")
    data["attachments"] = [{"filename": p.name, "saved_path": str(p)} for p in files_saved]
    # Resolution files come from the Resolve view's own Download button(s).
    if isinstance(data.get("resolution"), dict):
        data["resolution"]["attachments"] = [
            {"filename": p.name, "saved_path": str(p)} for p in res_saved]
    # Comment files are matched by name against everything downloaded this ticket.
    by_name = {p.name: p for p in (res_saved + files_saved)}
    for c in data.get("comments") or []:
        _match_paths(c.get("attachments"), by_name)
    return data

async def run_ticket_scrape_async(
    portal_url, username, password, ticket_ids, *,
    force=False, control, cb: TicketEngineCallbacks | None = None,
    workers=4, output_dir=None, browser_factory, page_portal_factory,
    login_once, parse_fn=parse_ticket_detail, parse_resolution_fn=parse_resolution, mode="light",
) -> dict:
    cb = cb or TicketEngineCallbacks()
    workers = max(1, min(10, int(workers or 1)))
    output_dir = Path(output_dir) if output_dir else TICKETS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    already = _load_scraped()
    total = len(ticket_ids)
    stats = {"total": total, "saved": 0, "skipped": 0, "not_found": 0, "failed": 0, "retried": 0}

    pending: asyncio.Queue = asyncio.Queue()
    for t in ticket_ids:
        pending.put_nowait(t)
    attempts: dict[str, int] = {}
    finished: set[str] = set()
    lock = asyncio.Lock()
    progress = [0]
    state_lock = asyncio.Lock()

    async def terminal(tid, status, key, meta=None):
        async with lock:
            if tid in finished:
                return
            finished.add(tid); stats[key] += 1; progress[0] += 1; p = progress[0]
        cb.on_progress(p, total); cb.on_ticket(tid, status)
        if meta is not None:
            cb.on_ticket_meta(*meta)

    async def drain_to_failed(reason: str):
        """Mark every still-pending ticket failed in ONE batch: bulk-update stats, emit a
        single summary log + one progress tick, and cap per-ticket GUI updates at
        _DRAIN_TICKET_CAP so a large collapse can't flood/hang the UI (bug-111)."""
        remaining = []
        while not pending.empty():
            remaining.append(pending.get_nowait())
        async with lock:
            fresh = [t for t in remaining if t not in finished]
            for t in fresh:
                finished.add(t); stats["failed"] += 1; progress[0] += 1
            p = progress[0]
        if not fresh:
            return
        cb.on_log("error", f"{len(fresh)} ticket(s) {reason} — marked failed.")
        cb.on_progress(p, total)
        for t in fresh[:_DRAIN_TICKET_CAP]:
            cb.on_ticket(t, "failed")

    # ── Browser provisioning differs by mode ─────────────────────────────────
    # light : ONE shared browser + ONE login; each worker opens a tab (page).
    # multi : each worker opens its OWN browser + logs in (separate windows).
    shared_browser = None
    if mode != "multi":
        shared_browser = await browser_factory().open()
        if not await login_once(shared_browser, username, password):
            cb.on_log("error", "Login failed; aborting.")
            await drain_to_failed("(login failed)")
            await shared_browser.close()
            cb.on_finished(stats)
            return stats

    async def _open_worker_page():
        """Acquire (own_browser_or_None, page) for a worker per mode. Raises on failure,
        always closing a just-opened browser first so a post-login new_page() error
        (or login failure) can't orphan it."""
        if mode == "multi":
            b = await browser_factory().open()
            try:
                if not await login_once(b, username, password):
                    raise RuntimeError("login failed")
                return b, await b.new_page()
            except Exception:
                try:
                    await b.close()
                except Exception:
                    pass
                raise
        return None, await shared_browser.new_page()

    async def worker(idx):
        prefix = f"[W{idx + 1}] " if workers > 1 else ""
        if control.cancelled:
            return
        own_browser = None
        page = None
        rebuilds = 0
        try:
            try:
                own_browser, page = await _open_worker_page()
            except Exception:
                cb.on_log("error", f"{prefix}could not start (browser/login) — worker exiting.")
                return
            portal = page_portal_factory(page)
            while True:
                await control.wait_if_paused_async()
                if control.cancelled:
                    cb.on_log("warning", f"{prefix}Cancelled."); break
                try:
                    tid = pending.get_nowait()
                except asyncio.QueueEmpty:
                    break
                async with lock:
                    if tid in finished:
                        continue
                if not force and tid in already:
                    cb.on_log("info", f"{prefix}[SKIP] #{tid}")
                    await terminal(tid, "skipped", "skipped"); continue
                async with lock:
                    attempts[tid] = attempts.get(tid, 0) + 1
                    n = attempts[tid]
                try:
                    res = await _fetch_ticket(portal, tid, output_dir, cb, parse_fn, parse_resolution_fn)
                    if res is _SESSION_EXPIRED:
                        cb.on_log("warning", f"{prefix}#{tid}: session expired")
                        raise RuntimeError("session expired")
                    # A page operation succeeded — reset the CONSECUTIVE-failure budget.
                    # (bug-111: this counter was never reset, so on a large batch a worker
                    # accumulated transient timeouts until it exhausted MAX_WORKER_REBUILDS
                    # and exited, collapsing the whole pool.)
                    rebuilds = 0
                    if res is None:
                        await terminal(tid, "failed", "failed")
                    elif res == "not_found":
                        await terminal(tid, "not_found", "not_found")
                    else:
                        save_ticket(res, output_dir)
                        async with state_lock:
                            _mark_scraped(tid); already.add(tid)
                        await terminal(tid, "ok", "saved",
                            meta=(tid, res.get("title", ""), len(res.get("attachments") or [])))
                        cb.on_log("info", f"{prefix}[OK] #{tid}: {res.get('title') or ''}")
                except Exception as exc:
                    if n < MAX_TICKET_ATTEMPTS:
                        cb.on_log("warning", f"{prefix}#{tid}: worker error ({type(exc).__name__}) "
                                             f"— redispatching ({n}/{MAX_TICKET_ATTEMPTS}).")
                        pending.put_nowait(tid)
                    else:
                        cb.on_log("error", f"{prefix}#{tid}: failed after {n} ({type(exc).__name__}).")
                        await terminal(tid, "failed", "failed")
                    rebuilds += 1
                    # tear down this worker's page (+ its own browser in multi mode)
                    try:
                        if page is not None:
                            await page.close()
                    except Exception:
                        pass
                    if own_browser is not None:
                        try:
                            await own_browser.close()
                        except Exception:
                            pass
                        own_browser = None
                    page = None
                    if rebuilds > MAX_WORKER_REBUILDS:
                        cb.on_log("error", f"{prefix}too many crashes — worker exiting.")
                        break
                    try:
                        own_browser, page = await _open_worker_page()
                        portal = page_portal_factory(page)
                    except Exception:
                        cb.on_log("error", f"{prefix}rebuild failed — worker exiting.")
                        page = None
                        break
        finally:
            try:
                if page is not None:
                    await page.close()
            except Exception:
                pass
            if own_browser is not None:
                try:
                    await own_browser.close()
                except Exception:
                    pass

    cb.on_log("info",
        f"--- Starting ticket scrape: {total} tickets"
        + (f" ({workers} workers, {mode})" if workers > 1 else "") + " ---")
    try:
        if total:
            n_workers = max(1, min(workers, total))
            await asyncio.gather(*(worker(i) for i in range(n_workers)))
            if not control.cancelled:
                await drain_to_failed("(not processed — all workers stopped)")
        async with lock:
            stats["retried"] = sum(1 for c in attempts.values() if c > 1)
        if total and stats["failed"] == total:
            cb.on_log("error",
                f"All {total} tickets failed — check credentials/network/portal.")
    finally:
        if shared_browser is not None:
            await shared_browser.close()
    cb.on_finished(stats)
    return stats
