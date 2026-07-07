"""Runs the async ticket/KB engines inside a QThread, bridging engine callbacks to Qt
signals so the GUI thread never blocks. Pause/cancel go through a shared RunControl."""
from __future__ import annotations
import asyncio

from PySide6.QtCore import QThread, Signal

from scraper.control import RunControl
from scraper.engine import EngineCallbacks
from scraper.ticket_engine import TicketEngineCallbacks
from scraper.ticket_engine_async import run_ticket_scrape_async
from scraper.kb_engine_async import run_kb_scrape_async


class AsyncTicketWorker(QThread):
    log = Signal(str, str)
    progress = Signal(int, int)
    ticket = Signal(str, str)
    ticket_meta = Signal(str, str, int)
    finished_report = Signal(dict)
    alert = Signal(str, str, str)

    def __init__(self, portal_url, username, password, ticket_ids, *,
                 force=False, workers=4, output_dir=None, control=None, mode="light",
                 browser_factory=None, page_portal_factory=None,
                 login_once=None, parse_fn=None, portal_kind="tradedesk", headless=False):
        super().__init__()
        self._url, self._user, self._pw = portal_url, username, password
        self._ids, self._force, self._workers = ticket_ids, force, workers
        self._out, self._mode = output_dir, mode
        self._headless = headless
        self.control = control or RunControl()
        self._bf, self._ppf = browser_factory, page_portal_factory
        self._login, self._parse = login_once, parse_fn
        self._parse_resolution = None
        self._portal_kind = portal_kind

    def run(self):
        cb = TicketEngineCallbacks(
            on_log=lambda lvl, msg: self.log.emit(lvl, msg),
            on_progress=lambda i, n: self.progress.emit(i, n),
            on_ticket=lambda tid, st: self.ticket.emit(tid, st),
            on_ticket_meta=lambda tid, t, n: self.ticket_meta.emit(tid, t, n),
            on_finished=lambda rep: self.finished_report.emit(rep),
            on_alert=lambda sev, title, body: self.alert.emit(sev, title, body),
        )
        bf, ppf, login = self._bf, self._ppf, self._login
        if bf is None:   # real wiring: select adapter by portal_kind
            from scraper.portal.async_browser import AsyncBrowser
            url = self._url
            if self._portal_kind == "contoso":
                from scraper.portal.contoso_portal import (
                    make_factory as ds_factory, contoso_login_once,
                )
                from scraper.parsers.contoso_parser import (
                    parse_ticket_detail as ds_detail,
                    parse_resolution as ds_res,
                )
                def bf():
                    b = AsyncBrowser(headless=self._headless)
                    b.base = url
                    return b
                ppf = ds_factory(url)
                login = contoso_login_once
                if self._parse is None:
                    self._parse = ds_detail
                self._parse_resolution = ds_res
            else:   # tradedesk (default)
                from scraper.portal.tradedesk_portal_async import make_factory, tradedesk_login_once
                def bf():
                    b = AsyncBrowser(headless=self._headless)
                    b.base = url
                    return b
                ppf = make_factory(url)
                login = tradedesk_login_once
        kwargs = {}
        if self._parse is not None:
            kwargs["parse_fn"] = self._parse
        if self._parse_resolution is not None:
            kwargs["parse_resolution_fn"] = self._parse_resolution
        # Resource sampler powers the engine's auto-tune + monitor (v4.0.3). Guarded:
        # if psutil is missing/unavailable, tuning is simply disabled (sampler=None).
        sampler = None
        try:
            from scraper.resmon import ResourceSampler
            sampler = ResourceSampler()
        except Exception:
            sampler = None
        try:
            asyncio.run(run_ticket_scrape_async(
                self._url, self._user, self._pw, self._ids,
                force=self._force, control=self.control, cb=cb,
                workers=self._workers, output_dir=self._out,
                browser_factory=bf, page_portal_factory=ppf, login_once=login,
                mode=self._mode, sampler=sampler, **kwargs))
        except Exception as exc:
            self.log.emit("error", f"Scrape thread error ({type(exc).__name__}).")
            # Spec 3.2: a crash inside the engine itself (not a per-ticket failure) must
            # surface as an alert popup, not just a log line — the GUI's alert box is
            # the operator-visible channel. Exception TYPE only (org policy: no message/PII).
            self.alert.emit("error", "Scrape crashed",
                "WHAT HAPPENED: the scrape engine hit an internal error "
                f"({type(exc).__name__}).\nWHAT IS PRESERVED: everything scraped "
                "before the crash is saved.\nWHAT TO DO: check the log file, then "
                "restart the scrape — already-scraped tickets are skipped "
                "automatically.")
            self.finished_report.emit({"total": len(self._ids), "saved": 0, "skipped": 0,
                                       "not_found": 0, "failed": len(self._ids), "retried": 0})
        finally:
            self._pw = ""   # drop the password from memory as soon as the run ends


class AsyncKBWorker(QThread):
    """Qt bridge for the async KB engine (v4.0.4, Task 5). Same shape as
    AsyncTicketWorker: forward EngineCallbacks events to Qt signals on the GUI
    thread's behalf, run the coroutine via asyncio.run(), and turn an engine-level
    crash into a visible alert instead of a silent thread death. The KB engine is
    public (no login) so there's no username/password to drop on exit."""
    log = Signal(str, str)
    status = Signal(str, dict)
    progress = Signal(str, str, int, int)
    finished_report = Signal(dict)
    alert = Signal(str, str, str)

    def __init__(self, space_cfgs, *, force=False, workers=4, output_base=None,
                 control=None, items=None, browser_factory=None, engine=None):
        super().__init__()
        self._space_cfgs = space_cfgs
        self._force = force
        self._workers = workers
        self._output_base = output_base
        self.control = control or RunControl()
        self._items = items
        self._bf = browser_factory
        self._engine = engine or run_kb_scrape_async

    def run(self):
        worker = self

        class _Callbacks(EngineCallbacks):
            def on_log(self, level, msg):
                worker.log.emit(level, msg)
            def on_status(self, product, stats):
                worker.status.emit(product, stats)
            def on_progress(self, product, version, idx, total):
                worker.progress.emit(product, version, idx, total)
            def on_alert(self, severity, title, body):
                worker.alert.emit(severity, title, body)

        cb = _Callbacks()
        bf = self._bf
        if bf is None:   # real wiring: headless per Settings (bug-111 scale lever)
            from scraper.portal.async_browser import AsyncBrowser
            from scraper import app_settings
            def bf():
                return AsyncBrowser(headless=app_settings.headless())
        # Resource sampler powers the engine's auto-tune (same guard as the ticket
        # worker): if psutil is missing/unavailable, tuning is simply disabled.
        sampler = None
        try:
            from scraper.resmon import ResourceSampler
            sampler = ResourceSampler()
        except Exception:
            sampler = None
        try:
            report = asyncio.run(self._engine(
                self._space_cfgs, force=self._force, control=self.control, cb=cb,
                workers=self._workers, output_base=self._output_base,
                browser_factory=bf, sampler=sampler, items=self._items))
            self.finished_report.emit(report)
        except Exception as exc:
            self.log.emit("error", f"KB scrape thread error ({type(exc).__name__}).")
            # Same crash-alert shape as AsyncTicketWorker (spec 3.2): a crash inside the
            # engine itself must surface as an alert popup, not just a log line.
            # Exception TYPE only (org policy: no message/PII).
            self.alert.emit("error", "KB scrape crashed",
                "WHAT HAPPENED: the KB scrape engine hit an internal error "
                f"({type(exc).__name__}).\nWHAT IS PRESERVED: every article scraped "
                "before the crash is saved.\nWHAT TO DO: check the log file, then "
                "restart the scrape — already-scraped articles are skipped "
                "automatically.")
            self.finished_report.emit({})
