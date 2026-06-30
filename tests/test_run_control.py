import sys, threading, time, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scraper.control import RunControl

def test_fresh_is_not_cancelled_or_paused():
    c = RunControl()
    assert c.cancelled is False and c.paused is False

def test_cancel_sets_flag():
    c = RunControl(); c.cancel()
    assert c.cancelled is True

def test_pause_then_resume_toggles_paused():
    c = RunControl(); c.pause()
    assert c.paused is True
    c.resume()
    assert c.paused is False

def test_wait_if_paused_returns_immediately_when_not_paused():
    c = RunControl()
    t0 = time.monotonic(); c.wait_if_paused(); assert time.monotonic() - t0 < 0.2

def test_wait_if_paused_unblocks_on_resume():
    c = RunControl(); c.pause()
    released = []
    def waiter():
        c.wait_if_paused(); released.append(True)
    th = threading.Thread(target=waiter); th.start()
    time.sleep(0.2); assert not released          # still blocked
    c.resume(); th.join(timeout=2); assert released  # unblocked

def test_wait_if_paused_returns_when_cancelled_even_if_paused():
    c = RunControl(); c.pause()
    released = []
    def waiter():
        c.wait_if_paused(); released.append(True)
    th = threading.Thread(target=waiter); th.start()
    time.sleep(0.2); c.cancel(); th.join(timeout=2)
    assert released

def test_wait_if_paused_async_yields_loop_then_resumes():
    # The async gate must NOT block the event loop while paused: our own
    # `await asyncio.sleep` runs concurrently (proving the loop ticks), and the
    # waiter only completes after resume().
    c = RunControl(); c.pause()
    async def scenario():
        w = asyncio.create_task(c.wait_if_paused_async(poll=0.01))
        await asyncio.sleep(0.05)
        assert not w.done()              # still waiting while paused, loop alive
        c.resume()
        await asyncio.wait_for(w, timeout=1.0)
        return w.done()
    assert asyncio.run(scenario()) is True

def test_wait_if_paused_async_returns_on_cancel():
    c = RunControl(); c.pause()
    async def scenario():
        w = asyncio.create_task(c.wait_if_paused_async(poll=0.01))
        await asyncio.sleep(0.05); c.cancel()
        await asyncio.wait_for(w, timeout=1.0)
        return w.done()
    assert asyncio.run(scenario()) is True
