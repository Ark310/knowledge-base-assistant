import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.throttle import AdaptiveGate


def _gate(maxp=8, **kw):
    return AdaptiveGate(maxp, window=8, min_permits=1, **kw)


def test_starts_unthrottled():
    g = _gate()
    assert g.permits == 8 and g.delay == 0.0 and g.tripped is False


def test_failures_reduce_permits_and_raise_backoff():
    g = _gate(down_at=0.4)
    for _ in range(8):              # a full window of failures
        g.record(False)
    assert g.permits < 8            # concurrency was reduced
    assert g.delay > 0.0            # backoff engaged


def test_sustained_failure_trips_breaker_at_floor():
    g = _gate(down_at=0.4, breaker_at=0.85)
    for _ in range(40):             # keep failing well past the window
        g.record(False)
    assert g.permits == g.min_permits   # throttled to the floor
    assert g.tripped is True            # breaker tripped for operator attention


def test_recovery_restores_permits_and_clears_backoff():
    g = _gate(down_at=0.4)
    for _ in range(8):
        g.record(False)
    assert g.permits < 8
    for _ in range(40):             # a long run of successes
        g.record(True)
    assert g.permits == g.max_permits
    assert g.delay == 0.0


def test_occasional_failures_do_not_trip():
    # 1 failure every 4 (25% < breaker) must NOT trip the breaker.
    g = _gate(down_at=0.4, breaker_at=0.85)
    for i in range(60):
        g.record(i % 4 != 0)        # 75% ok
    assert g.tripped is False


def test_consume_trip_is_once_then_resets_window():
    g = _gate(down_at=0.4, breaker_at=0.85)
    for _ in range(40):
        g.record(False)
    assert g.tripped is True
    assert g.consume_trip() is True     # one worker handles the trip
    assert g.consume_trip() is False    # others see it already consumed
    assert g.tripped is False           # cleared; fresh window after the pause
    # a single post-resume failure must not instantly re-trip (window was cleared)
    g.record(False)
    assert g.tripped is False


def test_min_permits_never_below_one():
    g = AdaptiveGate(3, window=4, min_permits=1)
    for _ in range(50):
        g.record(False)
    assert g.permits >= 1           # always at least one worker can proceed (no deadlock)
