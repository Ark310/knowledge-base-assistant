"""Single-run guard: only one scrape across all tabs (R7)."""
import scraper.run_registry as rr


def setup_function(_):
    rr.release(rr.owner() or "")


def test_acquire_release_cycle():
    assert rr.owner() is None
    assert rr.acquire("Tickets — tradedesk") is True
    assert rr.owner() == "Tickets — tradedesk"
    assert rr.acquire("Tickets — Legacy") is False      # blocked
    rr.release("Tickets — tradedesk")
    assert rr.owner() is None
    assert rr.acquire("Tickets — Legacy") is True


def test_release_by_non_owner_is_noop():
    rr.acquire("A")
    rr.release("B")
    assert rr.owner() == "A"


def test_reacquire_by_same_owner_is_true():
    rr.acquire("A")
    assert rr.acquire("A") is True
