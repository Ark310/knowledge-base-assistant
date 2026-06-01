"""V2.1 engine: orchestration with callbacks + cancellation. Shared by CLI and GUI."""
from __future__ import annotations
import json
import logging
from pathlib import Path

from scraper.config import (PRODUCTS, LIBRARY_BASE, STATE_FILE, REPORT_FILE, BASE_URL, COLUMN_SYNONYMS)
from scraper.core import Browser, StateTracker
from scraper.discovery import discover_versions
from scraper.parsers.universal import parse_page
from scraper.writers import json_writer, md_writer, index_generator
from scraper.config_writer import update_release_notes_urls
from scraper import config as config_module

log = logging.getLogger("scraper")


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False
    def cancel(self) -> None:
        self._cancelled = True
    def is_cancelled(self) -> bool:
        return self._cancelled


class EngineCallbacks:
    """No-op base; subclass and override to receive events."""
    def on_log(self, level: str, msg: str) -> None: pass
    def on_status(self, product: str, stats: dict) -> None: pass
    def on_progress(self, product: str, version: str, idx: int, total: int) -> None: pass
    def on_started(self, action: str) -> None: pass
    def on_finished(self, action: str, report: dict) -> None: pass


class LoggingCallbacks(EngineCallbacks):
    """Default CLI callbacks: route everything to the 'scraper' logger."""
    def on_log(self, level, msg):
        getattr(log, level if level in ("debug","info","warning","error","critical") else "info")(msg)
    def on_status(self, product, stats):
        log.info("%s status: %s", product, {k: v for k, v in stats.items() if k != "failed_urls"})
    def on_progress(self, product, version, idx, total):
        pass


class Engine:
    def __init__(self, callbacks: EngineCallbacks | None = None,
                 cancel_token: CancellationToken | None = None):
        self.cb = callbacks or EngineCallbacks()
        self.cancel = cancel_token or CancellationToken()

    def validate(self) -> bool:
        self.cb.on_started("validate")
        self.cb.on_log("info", "Validating space keys (dry-run, no scraping)...")
        ok = True
        report: dict = {}
        for key, cfg in PRODUCTS.items():
            try:
                items = discover_versions(cfg["space_key"])
                count = len(items)
                self.cb.on_log("info", f"  {key} [{cfg['space_key']}]: {count} versions")
                report[key] = {"space_key": cfg["space_key"], "count": count}
                if not items:
                    ok = False
            except Exception as exc:
                ok = False
                self.cb.on_log("error", f"  {key} [{cfg['space_key']}]: ERROR {exc}")
                report[key] = {"space_key": cfg["space_key"], "error": str(exc)}
        self.cb.on_log("info", f"Validation {'PASSED' if ok else 'FAILED'}")
        self.cb.on_finished("validate", report)
        return ok

    def discover_and_update_config(self) -> dict:
        self.cb.on_started("discover")
        self.cb.on_log("info", "Re-deriving release_notes_url for each product...")
        resolved: dict = {}
        for key, cfg in PRODUCTS.items():
            try:
                items = discover_versions(cfg["space_key"])
            except Exception as exc:
                self.cb.on_log("error", f"  {key}: discovery failed: {exc}")
                continue
            if items:
                resolved[key] = f"{BASE_URL}/display/{cfg['space_key']}"
                self.cb.on_log("info", f"  {key}: {len(items)} versions -> {resolved[key]}")
            else:
                self.cb.on_log("warning", f"  {key}: no versions found; leaving config unchanged")
        if resolved:
            config_path = Path(config_module.__file__)
            update_release_notes_urls(config_path, resolved)
            import importlib
            importlib.reload(config_module)
            for key, url in resolved.items():
                if config_module.PRODUCTS[key]["release_notes_url"] != url:
                    raise RuntimeError(f"config write verification failed for {key}")
            self.cb.on_log("info", "config.py updated and verified.")
        self.cb.on_finished("discover", resolved)
        return resolved

    def rebuild_indexes(self) -> None:
        self.cb.on_started("rebuild_indexes")
        self.cb.on_log("info", "Rebuilding indexes...")
        index_generator.generate_all(LIBRARY_BASE, PRODUCTS)
        self.cb.on_log("info", f"Indexes written to {LIBRARY_BASE}")
        self.cb.on_finished("rebuild_indexes", {})

    def scrape_product(self, product_key: str, force: bool = False) -> dict:
        return self._scrape_one(product_key, force, with_index_rebuild=True, action_label=f"scrape_{product_key}")

    def scrape_all(self, force: bool = False) -> dict:
        self.cb.on_started("scrape_all")
        report: dict = {}
        for key in PRODUCTS:
            if self.cancel.is_cancelled():
                self.cb.on_log("warning", "Cancelled — stopping scrape_all loop")
                break
            stats = self._scrape_one(key, force, with_index_rebuild=False, action_label=None)
            report[key] = stats
        try:
            self.rebuild_indexes()
        except Exception as exc:
            self.cb.on_log("error", f"Index rebuild failed: {exc}")
        self._write_report(report)
        self.cb.on_finished("scrape_all", report)
        return report

    def _scrape_one(self, product_key: str, force: bool, with_index_rebuild: bool,
                    action_label: str | None) -> dict:
        if action_label:
            self.cb.on_started(action_label)
        cfg = PRODUCTS[product_key]
        tracker = StateTracker(STATE_FILE)
        self.cb.on_log("info", f"=== {cfg['display_name']} ===")

        try:
            versions = discover_versions(cfg["space_key"])
        except Exception as exc:
            self.cb.on_log("error", f"{product_key}: discovery failed: {exc}")
            stats = {"discovered": 0, "new": 0, "skipped": 0, "failed": 0, "failed_urls": []}
            self.cb.on_status(product_key, stats)
            if action_label:
                self.cb.on_finished(action_label, stats)
            return stats

        self.cb.on_log("info", f"{product_key}: discovered {len(versions)} version page(s)")
        stats = {"discovered": len(versions), "new": 0, "skipped": 0, "failed": 0, "failed_urls": []}
        self.cb.on_status(product_key, stats)

        total = len(versions)
        with Browser() as browser:
            for idx, v in enumerate(versions, start=1):
                if self.cancel.is_cancelled():
                    self.cb.on_log("warning", f"{product_key}: cancelled before {v['version']}")
                    break

                ver, url, title = v["version"], v["url"], v["title"]
                self.cb.on_progress(product_key, ver, idx, total)

                if not force and tracker.is_scraped(product_key, ver):
                    stats["skipped"] += 1
                    self.cb.on_status(product_key, stats)
                    continue
                try:
                    browser.navigate(url)
                    browser.expand_confluence_macros()
                    shot = str(LIBRARY_BASE / product_key / "versions" / "screenshots"
                               / f"{json_writer.safe_name(ver)}.png")
                    browser.screenshot(shot)
                    data = parse_page(browser.get_content(), product_key, ver, title, url, shot,
                                      cfg["section_aliases"], COLUMN_SYNONYMS)
                    json_writer.save_version(data, LIBRARY_BASE)
                    md_writer.save_version(data, LIBRARY_BASE)
                    tracker.mark_scraped(product_key, ver, url)
                    stats["new"] += 1
                    summary = ", ".join(f"{k}={len(data[k])}" for k in
                                        ("enhancements", "bugs", "tasks", "schema_changes") if k in data) or "no sections"
                    self.cb.on_log("info", f"[OK] {ver} ({summary})")
                except Exception as exc:
                    stats["failed"] += 1
                    stats["failed_urls"].append(url)
                    self.cb.on_log("error", f"[FAIL] {ver}: {exc}")
                self.cb.on_status(product_key, stats)

        self.cb.on_log("info", f"{product_key} done: new={stats['new']} skipped={stats['skipped']} failed={stats['failed']}")
        if with_index_rebuild:
            try:
                self.rebuild_indexes()
            except Exception as exc:
                self.cb.on_log("error", f"Index rebuild failed: {exc}")
            self._write_report({product_key: stats})
        if action_label:
            self.cb.on_finished(action_label, stats)
        return stats

    def _write_report(self, report: dict) -> None:
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(json.dumps(report, indent=2), encoding="utf-8")
        self.cb.on_log("info", f"Run report written to {REPORT_FILE}")
