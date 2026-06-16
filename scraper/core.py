from __future__ import annotations
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Page, Browser as PWBrowser

log = logging.getLogger("scraper")

_BROWSER_DEAD_SIGNALS = (
    "target closed",
    "browser has been closed",
    "browser disconnected",
    "page closed",
    "connection closed",
    "context or browser has been closed",
)


def _is_browser_dead(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(sig in msg for sig in _BROWSER_DEAD_SIGNALS)


class Browser:
    """Headed or headless Chrome wrapper using Playwright sync API."""

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
        self._page.set_default_timeout(self.timeout_ms)
        return self

    def close(self):
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._pw:
            try:
                self._pw.stop()
            except Exception:
                pass

    def restart(self) -> None:
        """Kill the current browser and open a fresh one."""
        self.close()
        self.open()

    def is_alive(self) -> bool:
        """Return True if the browser page can still execute JavaScript."""
        try:
            self._page.evaluate("1")
            return True
        except Exception:
            return False

    def __enter__(self) -> "Browser":
        return self.open()

    def __exit__(self, *_):
        self.close()

    def navigate(self, url: str):
        last_exc = None
        for attempt in range(1, self.retries + 1):
            try:
                # domcontentloaded fires as soon as HTML is parsed — avoids
                # indefinite hangs from Confluence's background WebSocket polling
                # which prevents "networkidle" from ever firing.
                self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                self._page.wait_for_timeout(1_500)
                return
            except Exception as exc:
                last_exc = exc
                if _is_browser_dead(exc):
                    raise
                log.warning("navigate attempt %d/%d failed for %s: %s",
                            attempt, self.retries, url, exc)
                time.sleep(2 ** attempt)
        raise last_exc

    def fill(self, selector: str, value: str) -> None:
        self._page.fill(selector, value)

    def click(self, selector: str) -> None:
        self._page.click(selector)

    def wait_for_load(self, timeout_ms: int = 10_000) -> None:
        self._page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        self._page.wait_for_timeout(500)

    def expand_confluence_macros(self):
        for selector in [
            ".expand-control",
            "[data-macro-name='expand'] .expand-control-text",
            ".aui-expander-trigger",
            "a.expand-control",
        ]:
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
