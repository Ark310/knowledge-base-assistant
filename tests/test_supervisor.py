"""BrowserSupervisor — single-flight shared-browser recovery with bounded give-up."""
import asyncio

from scraper.supervisor import BrowserSupervisor
from scraper.ticket_engine import TicketEngineCallbacks


class _FakeBrowser:
    def __init__(self, fail_open=False):
        self.fail_open = fail_open
        self.closed = False
        self.pages = 0
    async def open(self):
        if self.fail_open:
            raise RuntimeError("no chrome")
        return self
    async def new_page(self):
        self.pages += 1
        return object()
    async def close(self):
        self.closed = True


def _sup(factory_results, login_results=None, max_consecutive=3):
    """factory_results: list of _FakeBrowser to hand out in order.
    login_results: list of bools per login attempt (default all True)."""
    made = []
    def factory():
        b = factory_results[len(made)] if len(made) < len(factory_results) else _FakeBrowser()
        made.append(b)
        return b
    logins = login_results or []
    async def login_once(browser, u, p):
        return logins.pop(0) if logins else True
    alerts = []
    cb = TicketEngineCallbacks(on_alert=lambda s, t, b: alerts.append((s, t, b)))
    sup = BrowserSupervisor(factory, login_once, "u", "p", cb,
                            max_consecutive=max_consecutive)
    return sup, made, alerts


def test_start_opens_and_logs_in():
    sup, made, _ = _sup([_FakeBrowser()])
    assert asyncio.run(sup.start()) is True
    assert sup.browser is made[0] and sup.generation == 0


def test_recover_replaces_browser_and_bumps_generation():
    async def main():
        sup, made, _ = _sup([_FakeBrowser(), _FakeBrowser()])
        await sup.start()
        ok = await sup.recover(sup.generation, "browser dead")
        return sup, made, ok
    sup, made, ok = asyncio.run(main())
    assert ok is True and sup.generation == 1
    assert made[0].closed is True and sup.browser is made[1]


def test_recover_is_single_flight_across_workers():
    async def main():
        sup, made, _ = _sup([_FakeBrowser(), _FakeBrowser()])
        await sup.start()
        gen = sup.generation
        results = await asyncio.gather(*(sup.recover(gen, "dead") for _ in range(5)))
        return sup, made, results
    sup, made, results = asyncio.run(main())
    assert all(results)
    assert sup.generation == 1          # ONE recovery, not five
    assert len(made) == 2               # start + one recovery


def test_gives_up_after_max_consecutive_failures_and_alerts_once():
    async def main():
        sup, _, alerts = _sup(
            [_FakeBrowser()] + [_FakeBrowser(fail_open=True)] * 5, max_consecutive=3)
        await sup.start()
        outs = []
        for _ in range(4):
            outs.append(await sup.recover(sup.generation, "dead"))
        return sup, alerts, outs
    sup, alerts, outs = asyncio.run(main())
    assert outs[:3] == [False, False, False] and sup.give_up is True
    assert outs[3] is False             # short-circuits once given up
    assert len(alerts) == 1             # exactly one popup, not four
    assert alerts[0][0] == "error"


def test_reset_give_up_allows_retry_after_resume():
    async def main():
        sup, _, _ = _sup([_FakeBrowser(), _FakeBrowser(fail_open=True),
                          _FakeBrowser(fail_open=True), _FakeBrowser(fail_open=True),
                          _FakeBrowser()], max_consecutive=3)
        await sup.start()
        for _ in range(3):
            await sup.recover(sup.generation, "dead")
        assert sup.give_up
        sup.reset_give_up()
        ok = await sup.recover(sup.generation, "retry after resume")
        return sup, ok
    sup, ok = asyncio.run(main())
    assert ok is True and sup.give_up is False and sup.generation == 1


def test_stale_generation_returns_immediately_without_restart():
    async def main():
        sup, made, _ = _sup([_FakeBrowser(), _FakeBrowser()])
        await sup.start()
        await sup.recover(0, "dead")            # real recovery -> gen 1
        ok = await sup.recover(0, "stale")      # caller saw gen 0: already fixed
        return sup, made, ok
    sup, made, ok = asyncio.run(main())
    assert ok is True and sup.generation == 1 and len(made) == 2


def test_relogin_failure_falls_back_to_full_recover():
    async def main():
        sup, made, _ = _sup([_FakeBrowser(), _FakeBrowser()],
                            login_results=[True, False, True])
        await sup.start()                        # login #1 True
        ok = await sup.relogin()                 # login #2 False -> full recover (login #3 True)
        return sup, made, ok
    sup, made, ok = asyncio.run(main())
    assert ok is True and len(made) == 2 and sup.generation == 1
