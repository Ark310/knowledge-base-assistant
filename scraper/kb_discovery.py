from __future__ import annotations
import re
from typing import Callable

from scraper.config import BASE_URL
from scraper.discovery import default_http_get


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug[:120] or "untitled"


def discover_articles(
    space_key: str,
    http_get: Callable[[str], dict] = default_http_get,
) -> list[dict]:
    """Return all pages in a Confluence space as article descriptors.

    Returns list of dicts: {"title", "url", "page_id", "slug"}
    Follows _links.next pagination until exhausted. Deduplicates by URL.
    """
    results: list[dict] = []
    seen_urls: set[str] = set()
    next_path: str | None = (
        f"/rest/api/content?spaceKey={space_key}&type=page&limit=100&start=0"
    )

    while next_path:
        url = next_path if next_path.startswith("http") else f"{BASE_URL}{next_path}"
        data = http_get(url)
        for item in data.get("results", []):
            title = item.get("title", "")
            webui = (item.get("_links") or {}).get("webui", "")
            full_url = webui if webui.startswith("http") else f"{BASE_URL}{webui}"
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            results.append({
                "title": title,
                "url": full_url,
                "page_id": str(item.get("id", "")),
                "slug": _slugify(title),
            })
        next_path = (data.get("_links") or {}).get("next")

    return results
