"""Adaptive concurrency gate for the async ticket engine (bug-111, v4.0.2).

Caps concurrent in-flight fetches and adapts the cap + an inter-ticket backoff from
recent outcomes: a burst of timeouts throttles the load (fewer concurrent tabs + a
growing delay) instead of letting the shared browser saturate and the pool collapse.
When failures persist even at minimum concurrency, `tripped` is set so the engine can
PAUSE for operator attention rather than mass-failing the remaining tickets.

The decision logic (`record`) is pure and synchronously unit-tested; `acquire`/`release`
wrap each ticket fetch and use an asyncio.Condition so permit changes take effect live.
In the happy path (no failures) the gate is a near no-op: permits stay at max, delay 0.
"""
from __future__ import annotations
import asyncio
from collections import deque


class AdaptiveGate:
    def __init__(self, max_permits: int, *, window: int = 20, min_permits: int = 1,
                 down_at: float = 0.40, up_at: float = 0.0, breaker_at: float = 0.85,
                 backoff_base: float = 0.5, backoff_max: float = 8.0):
        self.max_permits = max(1, int(max_permits))
        self.min_permits = max(1, min(int(min_permits), self.max_permits))
        self.permits = self.max_permits
        self.window = max(4, int(window))
        self.down_at, self.up_at, self.breaker_at = down_at, up_at, breaker_at
        self.backoff_base, self.backoff_max = backoff_base, backoff_max
        self.delay = 0.0
        self.tripped = False
        self._recent: deque[bool] = deque(maxlen=self.window)
        self._inflight = 0
        self._cond = asyncio.Condition()

    # ── pure decision logic (unit-tested) ────────────────────────────────────
    def _fail_ratio(self) -> float:
        if not self._recent:
            return 0.0
        return sum(1 for ok in self._recent if not ok) / len(self._recent)

    def record(self, ok: bool) -> None:
        """Record one outcome and recompute permits / backoff / breaker. No awaiting."""
        self._recent.append(bool(ok))
        fr = self._fail_ratio()
        if fr >= self.down_at and self.permits > self.min_permits:
            self.permits -= 1
            self.delay = min(self.backoff_max,
                             max(self.backoff_base, (self.delay * 2) or self.backoff_base))
        elif fr <= self.up_at:
            if self.permits < self.max_permits:
                self.permits += 1
            self.delay = 0.0 if self.permits >= self.max_permits else max(0.0, self.delay / 2)
        # Breaker: we've already throttled to the floor and failures STILL dominate a
        # full window -> something systemic (creds/network/portal). Flag for a pause.
        if (len(self._recent) >= self.window
                and self.permits <= self.min_permits
                and fr >= self.breaker_at):
            self.tripped = True

    def consume_trip(self) -> bool:
        """Atomically (asyncio is single-threaded; no awaits here) take a pending breaker
        trip: returns True once per trip and clears it + the window so that, after the
        operator resumes, the run gets a fresh window before it can trip again."""
        if self.tripped:
            self.tripped = False
            self._recent.clear()
            return True
        return False

    # ── async gate ────────────────────────────────────────────────────────────
    async def acquire(self) -> None:
        async with self._cond:
            while self._inflight >= self.permits:
                await self._cond.wait()
            self._inflight += 1
        if self.delay:
            await asyncio.sleep(self.delay)

    async def release(self, ok: bool) -> None:
        async with self._cond:
            self._inflight -= 1
            self.record(ok)
            self._cond.notify_all()
