"""Async Confluence article page ops (v4.0.4) — ports of core.Browser's sync
navigate/expand_confluence_macros/screenshot/get_content. Selectors and the
domcontentloaded rationale are identical (Confluence background WebSocket
polling means networkidle never fires). No retries here — the engine's
attempt/redispatch machinery owns retry policy."""
from __future__ import annotations
from pathlib import Path

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
    screenshot_path = Path(screenshot_path)
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(screenshot_path), full_page=True)
    return await page.content()
