"""Shared-browser supervisor (v4.0.3, bug-115/bug-116).

v4.0.2 light mode had ONE shared Chrome and no recovery path when IT died:
workers could only rebuild their tab (`shared_browser.new_page()` on a corpse),
so all of them exited and the engine mass-failed everything still queued
(2026-07-02: 28,620 tickets). The supervisor owns the shared browser and gives
workers a single-flight recovery: whoever hits the corpse first restarts
Chrome + re-logs-in while everyone else awaits the same lock, then all continue
on the new generation. Bounded: after `max_consecutive` failed recoveries it
sets give_up, emits ONE on_alert, and the engine pauses — pending tickets stay
queued for an operator Resume (reset_give_up + retry).

Logs exception TYPES only (org policy).
"""
from __future__ import annotations
import asyncio


class BrowserSupervisor:
    def __init__(self, browser_factory, login_once, username, password, cb, *,
                 max_consecutive: int = 3):
        self._factory = browser_factory
        self._login_once = login_once
        self._user, self._pw = username, password
        self._cb = cb
        self._max = max(1, max_consecutive)
        self._lock = asyncio.Lock()
        self._consecutive = 0
        self._alerted = False
        self.generation = 0
        self.give_up = False
        self.browser = None

    async def start(self) -> bool:
        try:
            self.browser = await self._factory().open()
            return bool(await self._login_once(self.browser, self._user, self._pw))
        except Exception as exc:
            self._cb.on_log("error", f"browser start failed ({type(exc).__name__}).")
            return False

    async def new_page(self):
        return await self.browser.new_page()

    async def relogin(self) -> bool:
        """Re-auth on the CURRENT browser (session expiry); full recover on failure."""
        async with self._lock:
            try:
                if await self._login_once(self.browser, self._user, self._pw):
                    self._consecutive = 0
                    return True
            except Exception:
                pass
        return await self.recover(self.generation, "session expired")

    async def recover(self, seen_generation: int, reason: str) -> bool:
        if self.give_up:
            return False
        async with self._lock:
            if self.generation != seen_generation:
                return True                     # someone else already recovered
            if self.give_up:
                return False
            self._cb.on_log("warning", f"shared browser recovery: {reason}")
            old, self.browser = self.browser, None
            if old is not None:
                try:
                    await old.close()
                except Exception:
                    pass
            try:
                b = await self._factory().open()
                if not await self._login_once(b, self._user, self._pw):
                    raise RuntimeError("re-login failed")
            except Exception as exc:
                self._consecutive += 1
                self._cb.on_log("error",
                    f"browser recovery {self._consecutive}/{self._max} failed "
                    f"({type(exc).__name__}).")
                if self._consecutive >= self._max:
                    self.give_up = True
                    if not self._alerted:
                        self._alerted = True
                        self._cb.on_alert("error", "Scrape paused — browser unrecoverable",
                            "WHAT HAPPENED: Chrome crashed and could not be restarted "
                            f"after {self._max} attempts.\n"
                            "LIKELY CAUSE: out of memory or a network/portal outage.\n"
                            "WHAT IS PRESERVED: everything scraped so far is saved; "
                            "remaining tickets are still queued (nothing was failed).\n"
                            "WHAT TO DO: close other programs or lower Workers, then "
                            "press Resume to retry. Stop cancels the run.")
                return False
            self.browser = b
            self.generation += 1
            self._consecutive = 0
            self._cb.on_log("info", f"shared browser recovered (generation {self.generation}).")
            return True

    def reset_give_up(self) -> None:
        self.give_up = False
        self._alerted = False
        self._consecutive = 0

    async def close(self) -> None:
        if self.browser is not None:
            try:
                await self.browser.close()
            except Exception:
                pass
