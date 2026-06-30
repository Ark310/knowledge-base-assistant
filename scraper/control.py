"""Run control shared by the scraper engines: cancel + pause/resume.

A single object lets the GUI stop a run (cancel) or hold it (pause) and continue
(resume). Workers call wait_if_paused() at item boundaries.
"""
from __future__ import annotations
import asyncio
import threading

class RunControl:
    def __init__(self) -> None:
        self._cancelled = False
        self._resume = threading.Event()
        self._resume.set()  # set == running; cleared == paused

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def paused(self) -> bool:
        return not self._resume.is_set()

    def cancel(self) -> None:
        self._cancelled = True
        self._resume.set()  # wake any waiters so they observe the cancel

    def pause(self) -> None:
        if not self._cancelled:
            self._resume.clear()

    def resume(self) -> None:
        self._resume.set()

    def is_cancelled(self) -> bool:   # back-compat alias for the v1/KB engines
        return self._cancelled

    def wait_if_paused(self) -> None:
        while not self._resume.is_set() and not self._cancelled:
            self._resume.wait(0.2)

    async def wait_if_paused_async(self, poll: float = 0.1) -> None:
        """Async pause gate for the asyncio ticket engine. Polls with asyncio.sleep
        so the event loop keeps ticking while paused — a blocking wait here would
        stall ALL worker coroutines on the shared loop, starving Playwright's
        browser I/O/keep-alive and disconnecting the browser mid-pause. Returns
        immediately on cancel."""
        while not self._resume.is_set() and not self._cancelled:
            await asyncio.sleep(poll)
