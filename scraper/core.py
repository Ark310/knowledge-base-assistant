from __future__ import annotations
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, Browser as PWBrowser

log = logging.getLogger("scraper")


class Browser:
    """Headed Chrome wrapper. Used only to render version pages and screenshot."""

    def __init__(self, headless: bool = False, timeout_ms: int = 30_000, retries: int = 3):
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.retries = retries
        self._pw = None
        self._browser: Optional[PWBrowser] = None
        self._page: Optional[Page] = None

    def open(self) -> "Browser":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless, channel="chrome")
        self._page = self._browser.new_page()
        return self

    def close(self):
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def __enter__(self) -> "Browser":
        return self.open()

    def __exit__(self, *_):
        self.close()

    def navigate(self, url: str):
        last_exc = None
        for attempt in range(1, self.retries + 1):
            try:
                self._page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
                return
            except Exception as exc:
                last_exc = exc
                log.warning("navigate attempt %d/%d failed for %s: %s",
                            attempt, self.retries, url, exc)
                time.sleep(2 ** attempt)
        raise last_exc

    def expand_confluence_macros(self):
        for selector in [".expand-control", "[data-macro-name='expand'] .expand-control-text",
                         ".aui-expander-trigger", "a.expand-control"]:
            try:
                for btn in self._page.locator(selector).all():
                    try:
                        btn.click(timeout=1_000)
                        self._page.wait_for_timeout(150)
                    except Exception:
                        pass
            except Exception:
                pass

    def screenshot(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._page.screenshot(path=path, full_page=True)

    def get_content(self) -> str:
        return self._page.content()

    def current_url(self) -> str:
        return self._page.url


class StateTracker:
    """Tracks scraped versions for incremental runs."""

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self._state = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def is_scraped(self, product: str, version: str) -> bool:
        return version in self._state.get(product, {})

    def mark_scraped(self, product: str, version: str, url: str):
        self._state.setdefault(product, {})[version] = {
            "url": url, "scraped_at": datetime.now().isoformat(),
        }
        self._save()

    def get_scraped_versions(self, product: str) -> dict:
        return self._state.get(product, {})
