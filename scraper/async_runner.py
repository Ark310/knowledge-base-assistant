"""Runs the async ticket engine inside a QThread, bridging engine callbacks to Qt
signals so the GUI thread never blocks. Pause/cancel go through a shared RunControl."""
from __future__ import annotations
import asyncio

from PySide6.QtCore import QThread, Signal

from scraper.control import RunControl
from scraper.ticket_engine import TicketEngineCallbacks
from scraper.ticket_engine_async import run_ticket_scrape_async


class AsyncTicketWorker(QThread):
    log = Signal(str, str)
    progress = Signal(int, int)
    ticket = Signal(str, str)
    ticket_meta = Signal(str, str, int)
    finished_report = Signal(dict)

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
        try:
            asyncio.run(run_ticket_scrape_async(
                self._url, self._user, self._pw, self._ids,
                force=self._force, control=self.control, cb=cb,
                workers=self._workers, output_dir=self._out,
                browser_factory=bf, page_portal_factory=ppf, login_once=login,
                mode=self._mode, **kwargs))
        except Exception as exc:
            self.log.emit("error", f"Scrape thread error ({type(exc).__name__}).")
            self.finished_report.emit({"total": len(self._ids), "saved": 0, "skipped": 0,
                                       "not_found": 0, "failed": len(self._ids), "retried": 0})
        finally:
            self._pw = ""   # drop the password from memory as soon as the run ends
