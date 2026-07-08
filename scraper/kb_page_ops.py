"""Async Confluence article page ops (v4.0.4) — ports of core.Browser's sync
navigate/expand_confluence_macros/screenshot/get_content. Selectors and the
domcontentloaded rationale are identical (Confluence background WebSocket
polling means networkidle never fires). No retries here — the engine's
attempt/redispatch machinery owns retry policy."""
from __future__ import annotations
import logging
from pathlib import Path

log = logging.getLogger("scraper")

# A per-article screenshot is supplementary reference material, not the article's
# data. Bound it well under the engine's ARTICLE_TIMEOUT_S so a slow render can't
# eat the whole budget, and treat failure as skippable (below).
_SCREENSHOT_TIMEOUT_MS = 20_000

_EXPAND_SELECTORS = [
    ".expand-control",
    "[data-macro-name='expand'] .expand-control-text",
    ".aui-expander-trigger",
    "a.expand-control",
]


async def expand_macros(page) -> None:
    for selector in _EXPAND_SELECTORS:
        try:
            for btn in await page.locator(selector).all():
                try:
                    await btn.click(timeout=1_000)
                    await page.wait_for_timeout(150)
                except Exception:
                    pass
        except Exception:
            pass


async def capture_article(page, url: str, screenshot_path: Path) -> str:
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(1_500)
    await expand_macros(page)
    # Capture the HTML (the article's actual data) FIRST, so a slow or failing
    # screenshot can never cost us the content by failing the article and burning
    # its retry budget — a heavy Confluence page can exceed the screenshot timeout
    # "waiting for fonts to load" even though its DOM parsed fine.
    html = await page.content()
    screenshot_path = Path(screenshot_path)
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(screenshot_path), full_page=True,
                              timeout=_SCREENSHOT_TIMEOUT_MS)
    except Exception as exc:
        # Best-effort: log the type only (org policy) and keep the article.
        log.warning("capture_article: screenshot skipped (%s)", type(exc).__name__)
    return html
