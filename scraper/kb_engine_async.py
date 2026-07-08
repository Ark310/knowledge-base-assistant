"""Async parallel KB engine — light mode ONLY (v4.0.4, Task 4).

Replaces the sequential sync KBEngine whose frozen-Chrome hang lost the operator
an article and made a KB run un-survivable. Mirrors the ticket engine's crash-
resilient worker-loop skeleton (scraper/ticket_engine_async.py): ONE shared browser
owned by a BrowserSupervisor + N tabs, a shared asyncio.Queue, bounded per-article
redispatch, single-flight shared-browser auto-recovery (a worker NEVER mass-fails on
browser death — bug-145), an AdaptiveGate circuit breaker that PAUSES (never drains)
on sustained failure, and exactly-once terminal accounting.

KB differs from tickets: the KB is PUBLIC (no login — login_once is a no-op), there
is no multi-window mode (drop own_browser), and each article is captured with a hard
outer ARTICLE_TIMEOUT_S ceiling around the browser-facing capture_article — the direct
fix for the frozen-tab regression. Cancel is silent (remaining articles stay unscraped
for the next run, never force-failed). Logs exception TYPE only (org policy)."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path

from scraper.kb_config import KB_SPACES, KB_LIBRARY_BASE
from scraper.kb_state import load_kb_state, kb_key
from scraper.kb_audit import audit_spaces
from scraper.kb_discovery import discover_articles
from scraper.kb_page_ops import capture_article
from scraper.parsers.article import parse_article
from scraper.writers.article_writer import save_article
from scraper.writers.kb_index_generator import generate_kb_index
from scraper.engine import EngineCallbacks
from scraper.supervisor import BrowserSupervisor
from scraper.throttle import AdaptiveGate
from scraper.kb_engine import KB_REPORT_FILE   # same file the tab's Retry button reads

# Hard outer ceiling for one article's goto+settle+expand+screenshot+content. The
# AsyncBrowser page carries a 30s default op timeout; this wait_for is THE frozen-tab
# guard — a hung content()/goto can't wedge a worker forever. Module-level so tests
# can shrink it.
ARTICLE_TIMEOUT_S = 90
MAX_ARTICLE_ATTEMPTS = 3
# Recycle a worker's tab every N successful articles to shed per-tab memory on long runs.
PAGE_RECYCLE_EVERY = 150
# Backoff between a worker's failed shared-browser recovery attempts (transient outage).
_RECOVER_RETRY_DELAY = 1.0
# How often the resource tuner re-applies the live worker ceiling + samples CPU/RAM.
_TUNER_INTERVAL = 2.0


async def _login_noop(browser, username, password) -> bool:
    """KB is public — no login. Must be a coroutine: BrowserSupervisor.start()/recover()
    do `await self._login_once(...)`, so a plain `lambda: True` would raise on await."""
    return True


def _new_stats() -> dict:
    return {"discovered": 0, "new": 0, "skipped": 0, "failed": 0, "failed_urls": []}


async def _scrape_article(page, cfg, art, output_base) -> None:
    """The per-article pipeline. ONLY the browser-facing capture_article is wrapped in
    wait_for (parse/save are local CPU work). asyncio.wait_for cancels the awaited task
    on timeout; the page may be in an odd state afterwards — fine, the worker's except
    path closes and rebuilds it, same as the ticket engine."""
    shot = Path(output_base) / cfg["product"] / cfg["lib_folder"] / "screenshots" / f"{art['slug']}.png"
    html = await asyncio.wait_for(
        capture_article(page, art["url"], shot), timeout=ARTICLE_TIMEOUT_S)
    data = parse_article(
        html, space_key=cfg["space_key"], space_name=cfg["display_name"],
        product=cfg["product"], title=art["title"], url=art["url"],
        screenshot_path=str(shot))
    save_article(data, output_base, cfg)


async def run_kb_scrape_async(
    space_cfgs: list[dict], *,
    force=False, control, cb: EngineCallbacks | None = None,
    workers=4, output_base=None,
    browser_factory,
    sampler=None, items=None,
    discover=None,
    state=None,
    run_audit=True,
) -> dict:
    cb = cb or EngineCallbacks()
    workers = max(1, min(10, int(workers or 1)))
    output_base = Path(output_base) if output_base else KB_LIBRARY_BASE
    state = state if state is not None else load_kb_state()
    discover = discover if discover is not None else discover_articles

    pending: asyncio.Queue = asyncio.Queue()
    space_stats: dict[str, dict] = {}
    failed_articles: list[dict] = []

    # ── Build the work queue ─────────────────────────────────────────────────
    # items mode (the Retry path) skips discovery entirely; per-space stats are still
    # emitted for the spaces present in items (discovered = count of queued items).
    if items is not None:
        scoped_cfgs: list[dict] = []
        seen: set[str] = set()
        for cfg, art in items:
            sk = cfg["space_key"]
            st = space_stats.setdefault(sk, _new_stats())
            st["discovered"] += 1
            pending.put_nowait((cfg, art))
            if sk not in seen:
                seen.add(sk); scoped_cfgs.append(cfg)
        for sk in space_stats:
            cb.on_status(sk, space_stats[sk])
    else:
        scoped_cfgs = list(space_cfgs)
        for cfg in space_cfgs:
            sk = cfg["space_key"]
            st = _new_stats()
            space_stats[sk] = st
            cb.on_log("info", f"=== {cfg['display_name']} ({sk}) ===")
            try:
                arts = discover(sk)
            except Exception as exc:
                cb.on_log("error", f"{sk}: discovery failed ({type(exc).__name__}).")
                cb.on_status(sk, st)             # discovered stays 0
                continue
            st["discovered"] = len(arts)
            cb.on_log("info", f"{sk}: {len(arts)} article(s) discovered")
            cb.on_status(sk, st)
            for art in arts:
                pending.put_nowait((cfg, art))

    total = pending.qsize()

    # ── Shared worker state ──────────────────────────────────────────────────
    n_workers = max(1, min(workers, total)) if total else 0
    exited_workers: set[int] = set()
    attempts: dict[str, int] = {}
    finished: set[str] = set()
    lock = asyncio.Lock()
    state_lock = asyncio.Lock()
    progress = [0]

    async def terminal(cfg, art, key, kind, exc=None) -> bool:
        """Exactly-once accounting: bump the per-space stat + overall progress and emit
        on_status/on_progress. Returns True the first time a key reaches a terminal."""
        sk = cfg["space_key"]
        async with lock:
            if key in finished:
                return False
            finished.add(key)
            st = space_stats[sk]
            st[kind] += 1
            if kind == "failed":
                st["failed_urls"].append(art["url"])
                failed_articles.append({
                    "space_key": sk, "title": art["title"], "url": art["url"],
                    "slug": art["slug"],
                    "error_type": type(exc).__name__ if exc is not None else "Unknown"})
            progress[0] += 1
            done = progress[0]
        cb.on_status(sk, st)
        cb.on_progress(sk, art["title"], done, total)
        return True

    async def worker(idx, gate):
        prefix = f"[W{idx + 1}] " if n_workers > 1 else ""
        if control.cancelled:
            return
        page = None
        since_recycle = 0

        async def _recover_page():
            """(Re)acquire this worker's tab. NEVER exits on infrastructure failure
            (bug-145): if the shared browser is the corpse, run single-flight supervisor
            recovery; if the supervisor gave up, PAUSE (it already emitted ONE alert) and
            wait for the operator to Resume (retry) or Stop. Returns False only on cancel."""
            nonlocal page
            while page is None and not control.cancelled:
                # Capture the generation BEFORE the attempt: a new_page() on a dead
                # browser can hang while ANOTHER worker completes recovery (gen G->G+1);
                # reading it after would let this stale failure needlessly re-recover.
                gen = supervisor.generation
                try:
                    page = await supervisor.new_page()
                except Exception:
                    if not await supervisor.recover(gen, "worker page rebuild failed"):
                        if supervisor.give_up:
                            control.pause()             # alert already emitted (once)
                            await control.wait_if_paused_async()
                            if control.cancelled:
                                return False
                            supervisor.reset_give_up()  # operator resumed: retry
                        else:
                            await asyncio.sleep(_RECOVER_RETRY_DELAY)
            return not control.cancelled

        try:
            if not await _recover_page():
                return
            while True:
                await control.wait_if_paused_async()
                if control.cancelled:
                    cb.on_log("warning", f"{prefix}Cancelled."); break
                # ── Live worker target (park / un-park) ───────────────────────
                # A lowered live worker-slider parks surplus workers: they drop their tab
                # (hold no browser resource) and poll without pulling work. Worker 0 is
                # always active. Parked workers exit once the queue is drained OR every
                # active-slot worker has exited, so asyncio.gather() can complete.
                target = control.target_workers or workers
                if idx >= max(1, min(workers, target)):
                    if page is not None:
                        try:
                            await page.close()
                        except Exception:
                            pass
                        page = None
                    active_n = min(max(1, min(workers, target)), n_workers)
                    if (pending.empty()
                            or all(i in exited_workers for i in range(active_n))):
                        break
                    await asyncio.sleep(0.5)
                    continue
                if page is None and not await _recover_page():
                    break
                try:
                    cfg, art = pending.get_nowait()
                except asyncio.QueueEmpty:
                    break
                key = kb_key(cfg["space_key"], art["slug"])
                async with lock:
                    if key in finished:
                        continue
                if not force and key in state.ids:
                    cb.on_log("info", f"{prefix}[SKIP] {art['title']}")
                    await terminal(cfg, art, key, "skipped"); continue
                async with lock:
                    attempts[key] = attempts.get(key, 0) + 1
                    n = attempts[key]
                # Adaptive gate: caps concurrent captures + applies backoff so a timeout
                # burst throttles load instead of saturating the shared browser.
                await gate.acquire()
                ok = False
                broke = False
                try:
                    await _scrape_article(page, cfg, art, output_base)
                    ok = True
                    if await terminal(cfg, art, key, "new"):
                        async with state_lock:
                            state.mark(key)
                        cb.on_log("info", f"{prefix}[OK] {art['title']}")
                        since_recycle += 1
                except Exception as exc:
                    if n < MAX_ARTICLE_ATTEMPTS:
                        cb.on_log("warning", f"{prefix}{art['title']}: error "
                                  f"({type(exc).__name__}) — redispatching ({n}/{MAX_ARTICLE_ATTEMPTS}).")
                        pending.put_nowait((cfg, art))
                    else:
                        cb.on_log("error", f"{prefix}{art['title']}: failed after {n} "
                                  f"({type(exc).__name__}).")
                        await terminal(cfg, art, key, "failed", exc=exc)
                    # Tear down this worker's (possibly wedged) tab; if the SHARED browser
                    # is the corpse, run single-flight supervisor recovery (never exit).
                    try:
                        if page is not None:
                            await page.close()
                    except Exception:
                        pass
                    page = None
                    since_recycle = 0
                    if not await _recover_page():
                        broke = True
                finally:
                    await gate.release(ok)
                if broke:
                    break
                # Circuit breaker: failures persisted even after throttling to the floor.
                # PAUSE for operator attention rather than burning through the queue.
                if gate.consume_trip():
                    cb.on_log("error", f"{prefix}⚠ Sustained failures — run PAUSED. "
                              "Check your network, lower Workers, then Resume.")
                    cb.on_alert("warning", "KB scrape paused — sustained failures",
                        "WHAT HAPPENED: recent articles keep failing even after "
                        "throttling down.\nLIKELY CAUSE: network problems or machine "
                        "overload.\nWHAT IS PRESERVED: everything scraped so far is "
                        "saved; remaining articles are still queued.\nWHAT TO DO: check "
                        "your network, lower Workers, then press Resume.")
                    control.pause()
                    continue
                # Periodic tab recycle: reopen a fresh page in the same context (no login).
                if ok and page is not None and since_recycle >= PAGE_RECYCLE_EVERY:
                    since_recycle = 0
                    try:
                        await page.close()
                    except Exception:
                        pass
                    page = None
                    if not await _recover_page():
                        break
        finally:
            exited_workers.add(idx)   # parked workers watch this (see park block)
            try:
                if page is not None:
                    await page.close()
            except Exception:
                pass

    cb.on_log("info", f"--- Starting KB scrape: {total} article(s)"
              + (f" ({workers} workers)" if workers > 1 else "") + " ---")

    supervisor = None
    audit = None
    try:
        if total:
            # No login: KB is public. Supervisor owns the ONE shared browser + recovery.
            supervisor = BrowserSupervisor(
                browser_factory, _login_noop, "", "", cb)
            if not await supervisor.start():
                cb.on_log("error", "KB scrape: browser could not start.")
                cb.on_alert("error", "KB scrape could not start",
                    "WHAT HAPPENED: the browser failed to launch.\n"
                    "WHAT TO DO: check that Chrome is installed and reachable, then "
                    "start the scrape again. Nothing was lost — no articles were failed.")
            else:
                gate = AdaptiveGate(n_workers)

                async def _tuner():
                    while True:
                        await asyncio.sleep(_TUNER_INTERVAL)
                        if control.cancelled:
                            return
                        target = control.target_workers or workers
                        gate.set_ceiling(max(1, min(workers, target)))
                        if sampler is not None:
                            try:
                                snap = sampler.sample()
                                gate.tune(snap.cpu_pct, snap.ram_free_mb)
                            except Exception:
                                pass

                tuner = asyncio.ensure_future(_tuner())
                try:
                    await asyncio.gather(*(worker(i, gate) for i in range(n_workers)))
                finally:
                    tuner.cancel()
                    try:
                        await tuner
                    except asyncio.CancelledError:
                        pass

        # ── Finalize (skipped on cancel: the operator stopped intentionally) ──
        if not control.cancelled:
            try:
                generate_kb_index(output_base, KB_SPACES)
            except Exception as exc:
                cb.on_log("error", f"KB index rebuild failed ({type(exc).__name__}).")
            if run_audit:
                try:
                    audit = audit_spaces(scoped_cfgs, output_base)
                except Exception as exc:
                    cb.on_log("error", f"KB audit failed ({type(exc).__name__}).")
                    audit = None
    finally:
        try:
            state.flush()
        except Exception:
            pass
        if supervisor is not None:
            await supervisor.close()

    totals = {
        "discovered": sum(s["discovered"] for s in space_stats.values()),
        "new": sum(s["new"] for s in space_stats.values()),
        "skipped": sum(s["skipped"] for s in space_stats.values()),
        "failed": sum(s["failed"] for s in space_stats.values()),
    }
    report = {"spaces": space_stats, "failed_articles": failed_articles,
              "audit": audit, "totals": totals}

    if not control.cancelled:
        # Post-run audit summary alert (static text + counts only).
        if run_audit and audit is not None:
            missing = audit.get("totals", {}).get("missing", 0)
            failed = totals["failed"]
            if missing or failed:
                cb.on_alert("warning", "KB scrape finished — items need attention",
                    f"WHAT HAPPENED: {missing} article(s) missing on disk and "
                    f"{failed} failed.\nWHAT TO DO: click 'Retry Failures' to re-scrape "
                    "exactly those articles.")
            else:
                discovered = audit.get("totals", {}).get("discovered", 0)
                cb.on_alert("info", "KB scrape complete — library verified",
                    f"All {discovered} discovered article(s) for the scraped spaces "
                    "are present on disk.")
        try:
            KB_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
            KB_REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception as exc:
            cb.on_log("error", f"KB report write failed ({type(exc).__name__}).")

    return report
