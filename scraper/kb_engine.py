# scraper/kb_engine.py
from __future__ import annotations
import json
import logging
from pathlib import Path

from scraper.kb_config import (
    KB_SPACES, KB_SPACES_BY_KEY, KB_PRODUCT_GROUPS, KB_ARTICLES_STATE_FILE, KB_LIBRARY_BASE,
)
from scraper.config import REPORT_FILE
from scraper.core import Browser, StateTracker
from scraper.engine import EngineCallbacks, CancellationToken
from scraper.kb_discovery import discover_articles
from scraper.parsers.article import parse_article
from scraper.writers.article_writer import save_article, safe_slug
from scraper.writers.kb_index_generator import generate_kb_index

log = logging.getLogger("scraper")

KB_REPORT_FILE = REPORT_FILE.parent / "last_kb_run_report.json"


class KBEngine:
    def __init__(
        self,
        callbacks: EngineCallbacks | None = None,
        cancel_token: CancellationToken | None = None,
        output_base: Path | None = None,
    ):
        self.cb = callbacks or EngineCallbacks()
        self.cancel = cancel_token or CancellationToken()
        self.output_base = Path(output_base) if output_base else KB_LIBRARY_BASE

    def validate(self) -> bool:
        self.cb.on_started("validate_kb")
        self.cb.on_log("info", "Validating KB spaces (dry-run, no scraping)...")
        ok = True
        report: dict = {}
        for cfg in KB_SPACES:
            key = cfg["space_key"]
            try:
                items = discover_articles(key)
                count = len(items)
                self.cb.on_log("info", f"  {key} [{cfg['display_name']}]: {count} articles")
                report[key] = {"display_name": cfg["display_name"], "count": count}
                if not items:
                    ok = False
            except Exception as exc:
                ok = False
                self.cb.on_log("error", f"  {key}: ERROR {exc}")
                report[key] = {"display_name": cfg["display_name"], "error": str(exc)}
        self.cb.on_log("info", f"KB Validation {'PASSED' if ok else 'FAILED'}")
        self.cb.on_finished("validate_kb", report)
        return ok

    def rebuild_indexes(self) -> None:
        self.cb.on_started("rebuild_kb_indexes")
        self.cb.on_log("info", "Rebuilding KB indexes...")
        generate_kb_index(self.output_base, KB_SPACES)
        self.cb.on_log("info", f"KB indexes written to {self.output_base}")
        self.cb.on_finished("rebuild_kb_indexes", {})

    def scrape_space(self, space_key: str, force: bool = False) -> dict:
        return self._scrape_one(
            space_key, force,
            with_index_rebuild=True,
            action_label=f"scrape_kb_{space_key}",
        )

    def scrape_all(self, force: bool = False) -> dict:
        self.cb.on_started("scrape_kb_all")
        report: dict = {}
        for cfg in KB_SPACES:
            self.cancel.wait_if_paused()
            if self.cancel.is_cancelled():
                self.cb.on_log("warning", "Cancelled — stopping scrape_kb_all")
                break
            stats = self._scrape_one(
                cfg["space_key"], force, with_index_rebuild=False, action_label=None
            )
            report[cfg["space_key"]] = stats
        try:
            self.rebuild_indexes()
        except Exception as exc:
            self.cb.on_log("error", f"KB index rebuild failed: {exc}")
        self._write_report(report)
        self.cb.on_finished("scrape_kb_all", report)
        return report

    def scrape_family(self, product_label: str, force: bool = False) -> dict:
        """Scrape only the spaces belonging to one KB product family."""
        self.cb.on_started("scrape_kb_family")
        report: dict = {}
        for cfg in KB_PRODUCT_GROUPS[product_label]:
            self.cancel.wait_if_paused()
            if self.cancel.is_cancelled():
                self.cb.on_log("warning", "Cancelled — stopping scrape_kb_family")
                break
            stats = self._scrape_one(
                cfg["space_key"], force, with_index_rebuild=False, action_label=None
            )
            report[cfg["space_key"]] = stats
        try:
            self.rebuild_indexes()
        except Exception as exc:
            self.cb.on_log("error", f"KB index rebuild failed: {exc}")
        self._write_report(report)
        self.cb.on_finished("scrape_kb_family", report)
        return report

    def _scrape_one(
        self, space_key: str, force: bool,
        with_index_rebuild: bool, action_label: str | None,
    ) -> dict:
        if action_label:
            self.cb.on_started(action_label)

        cfg = KB_SPACES_BY_KEY[space_key]
        tracker = StateTracker(KB_ARTICLES_STATE_FILE)
        self.cb.on_log("info", f"=== {cfg['display_name']} ({space_key}) ===")

        try:
            articles = discover_articles(space_key)
        except Exception as exc:
            self.cb.on_log("error", f"{space_key}: discovery failed: {exc}")
            stats = {"discovered": 0, "new": 0, "skipped": 0, "failed": 0, "failed_urls": []}
            self.cb.on_status(space_key, stats)
            if action_label:
                self.cb.on_finished(action_label, stats)
            return stats

        self.cb.on_log("info", f"{space_key}: {len(articles)} article(s) discovered")
        stats = {
            "discovered": len(articles), "new": 0,
            "skipped": 0, "failed": 0, "failed_urls": [],
        }
        self.cb.on_status(space_key, stats)

        total = len(articles)
        screenshot_dir = self.output_base / cfg["product"] / cfg["lib_folder"] / "screenshots"

        with Browser() as browser:
            for idx, art in enumerate(articles, start=1):
                self.cancel.wait_if_paused()
                if self.cancel.is_cancelled():
                    self.cb.on_log("warning", f"{space_key}: cancelled before '{art['title']}'")
                    break

                title, url, slug = art["title"], art["url"], art["slug"]
                self.cb.on_progress(space_key, title, idx, total)

                if not force and tracker.is_scraped(space_key, slug):
                    stats["skipped"] += 1
                    self.cb.on_status(space_key, stats)
                    continue

                try:
                    browser.navigate(url)
                    browser.expand_confluence_macros()
                    shot = str(screenshot_dir / f"{slug}.png")
                    browser.screenshot(shot)
                    data = parse_article(
                        browser.get_content(),
                        space_key=space_key,
                        space_name=cfg["display_name"],
                        product=cfg["product"],
                        title=title,
                        url=url,
                        screenshot_path=shot,
                    )
                    save_article(data, self.output_base, cfg)
                    tracker.mark_scraped(space_key, slug, url)
                    stats["new"] += 1
                    self.cb.on_log("info", f"[OK] {title}")
                except Exception as exc:
                    stats["failed"] += 1
                    stats["failed_urls"].append(url)
                    self.cb.on_log("error", f"[FAIL] {title}: {exc}")
                    # If the browser died (crash / frozen tab), restart it so
                    # remaining articles in this space can still be scraped.
                    # The failed article is NOT marked scraped, so it will be
                    # retried automatically on the next run.
                    if not browser.is_alive():
                        self.cb.on_log("warning", f"{space_key}: browser died — restarting...")
                        try:
                            browser.restart()
                            self.cb.on_log("info", f"{space_key}: browser restarted, resuming.")
                        except Exception as restart_exc:
                            self.cb.on_log("error", f"{space_key}: browser restart failed: {restart_exc}")
                            break
                self.cb.on_status(space_key, stats)

        self.cb.on_log(
            "info",
            f"{space_key} done: new={stats['new']} skipped={stats['skipped']} failed={stats['failed']}",
        )
        if with_index_rebuild:
            try:
                self.rebuild_indexes()
            except Exception as exc:
                self.cb.on_log("error", f"KB index rebuild failed: {exc}")
            self._write_report({space_key: stats})
        if action_label:
            self.cb.on_finished(action_label, stats)
        return stats

    def _write_report(self, report: dict) -> None:
        KB_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        KB_REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self.cb.on_log("info", f"KB run report written to {KB_REPORT_FILE}")
