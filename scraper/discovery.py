from __future__ import annotations
import json
import re
import urllib.request
from typing import Callable, Optional

from scraper.config import BASE_URL

# Two or more dot-separated number groups => a real version (e.g. 2.0.2.1, 3.0.1.9).
# "Web 4.0" (single dot) is intentionally excluded.
_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)+")


def extract_version(title: str) -> Optional[str]:
    m = _VERSION_RE.search(title or "")
    return m.group(0) if m else None


def is_version_title(title: str) -> bool:
    return extract_version(title) is not None


def default_http_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 kb-scraper"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _unique_version(title: str, m: re.Match, taken: set[str], idx: int) -> str:
    """Return a version string unique within `taken`. The base is the numeric
    match; on collision (e.g. 'Version 2.4.0.10' vs '...2.4.0.10 EXT') append a
    slug of the title's trailing text, or the page index as a last resort."""
    base = m.group(0)
    if base not in taken:
        return base
    tail = title[m.end():].strip()
    suffix = re.sub(r"[^A-Za-z0-9]+", "-", tail).strip("-") or str(idx)
    candidate = f"{base}-{suffix}"
    while candidate in taken:
        candidate = f"{base}-{suffix}-{idx}"
        idx += 1
    return candidate


def discover_versions(space_key: str, http_get: Callable[[str], dict] = default_http_get) -> list[dict]:
    """
    Return a clean, de-duplicated list of version pages for a Confluence space:
      [{"version": "2.0.2.1", "title": "...", "url": "https://...", "page_id": "123"}, ...]
    Follows _links.next pagination until exhausted. Version strings are made
    unique so distinct pages never share a filename.
    """
    results: list[dict] = []
    seen_urls: set[str] = set()
    taken_versions: set[str] = set()
    next_path = f"/rest/api/content?spaceKey={space_key}&type=page&limit=100&start=0"
    idx = 0

    while next_path:
        url = next_path if next_path.startswith("http") else f"{BASE_URL}{next_path}"
        data = http_get(url)
        for item in data.get("results", []):
            idx += 1
            title = item.get("title", "")
            m = _VERSION_RE.search(title)
            if not m:
                continue
            webui = (item.get("_links", {}) or {}).get("webui", "")
            full_url = webui if webui.startswith("http") else f"{BASE_URL}{webui}"
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            version = _unique_version(title, m, taken_versions, idx)
            taken_versions.add(version)
            results.append({
                "version": version,
                "title": title,
                "url": full_url,
                "page_id": str(item.get("id", "")),
            })
        next_path = (data.get("_links", {}) or {}).get("next")

    return results
