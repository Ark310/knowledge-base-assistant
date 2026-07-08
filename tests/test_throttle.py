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


# ── v4.0.3: resource tune + live ceiling ─────────────────────────────────────

def test_tune_steps_down_on_high_cpu():
    g = AdaptiveGate(8)
    g.tune(cpu_pct=95.0, ram_free_mb=4000.0)
    assert g.permits == 7

def test_tune_steps_down_on_low_ram():
    g = AdaptiveGate(8)
    g.tune(cpu_pct=10.0, ram_free_mb=500.0)
    assert g.permits == 7

def test_tune_steps_up_with_headroom_but_never_past_ceiling():
    g = AdaptiveGate(8)
    g.permits = 4
    g.tune(cpu_pct=30.0, ram_free_mb=6000.0)
    assert g.permits == 5
    g.permits = 8
    g.tune(cpu_pct=30.0, ram_free_mb=6000.0)
    assert g.permits == 8

def test_tune_holds_in_dead_band():
    g = AdaptiveGate(8)
    g.permits = 5
    g.tune(cpu_pct=80.0, ram_free_mb=1000.0)   # between thresholds: no change
    assert g.permits == 5

def test_tune_respects_min_permits():
    g = AdaptiveGate(2)
    g.permits = 1
    g.tune(cpu_pct=99.0, ram_free_mb=100.0)
    assert g.permits == 1

def test_set_ceiling_lowers_and_raises_live():
    g = AdaptiveGate(8)
    g.set_ceiling(3)
    assert g.max_permits == 3 and g.permits == 3
    g.set_ceiling(6)
    assert g.max_permits == 6
    assert g.permits == 3          # permits climb back via tune/record, not instantly

def test_set_ceiling_clamps_to_at_least_one():
    g = AdaptiveGate(8)
    g.set_ceiling(0)
    assert g.max_permits == 1 and g.permits == 1
