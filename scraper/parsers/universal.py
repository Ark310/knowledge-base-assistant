from __future__ import annotations
import re
from datetime import datetime
from typing import Optional

from bs4 import BeautifulSoup, Tag

_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)+")
_HEADINGS = ("h1", "h2", "h3", "h4")


def _extract_version(title: str) -> Optional[str]:
    m = _VERSION_RE.search(title or "")
    return m.group(0) if m else None


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "col"


def normalize_header(header: str, synonyms: dict[str, str]) -> str:
    key = _collapse_ws(header).lower()
    if key.startswith("risk assessment"):
        return "risk"
    if key in synonyms:
        return synonyms[key]
    return _slugify(key)


def _find_content(soup: BeautifulSoup) -> Tag:
    for selector in ["#main-content", ".wiki-content", "#content", "main", "article"]:
        el = soup.select_one(selector)
        if el:
            return el
    return soup


def _table_after(heading: Tag) -> Optional[Tag]:
    """Walk siblings after a heading until the next heading; return the first
    table that is either a sibling or nested inside a sibling (Confluence wraps
    tables in div.table-wrap)."""
    node = heading.next_sibling
    while node is not None:
        if isinstance(node, Tag):
            if node.name in _HEADINGS:
                return None
            if node.name == "table":
                return node
            inner = node.find("table")
            if inner:
                return inner
        node = node.next_sibling
    return None


def _parse_table(table: Tag, synonyms: dict[str, str]) -> list[dict]:
    rows = table.find_all("tr")
    if len(rows) < 2:
        return []
    headers = [normalize_header(c.get_text(separator=" ", strip=True), synonyms)
               for c in rows[0].find_all(["th", "td"])]
    out: list[dict] = []
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        row: dict = {}
        for i, cell in enumerate(cells):
            if i < len(headers):
                row[headers[i]] = _collapse_ws(cell.get_text(separator=" ", strip=True))
        if any(v for v in row.values()):
            out.append(row)
    return out


def _resolve_section(heading_text: str, section_aliases: dict[str, list[str]]) -> Optional[str]:
    text = _collapse_ws(heading_text).lower()
    for canonical, aliases in section_aliases.items():
        if any(alias == text or alias in text for alias in aliases):
            return canonical
    return None


def parse_page(
    html: str,
    product: str,
    version: str,
    title: str,
    url: str,
    screenshot_path: str,
    section_aliases: dict[str, list[str]],
    column_synonyms: dict[str, str],
) -> dict:
    soup = BeautifulSoup(html, "lxml")
    content = _find_content(soup)

    result: dict = {
        "product": product,
        "version": version,
        "title": title,
        "url": url,
        "scraped_at": datetime.now().isoformat(),
        "screenshot": screenshot_path,
    }

    for heading in content.find_all(list(_HEADINGS)):
        heading_text = heading.get_text(separator=" ", strip=True)
        if "table of contents" in heading_text.lower():
            continue
        section = _resolve_section(heading_text, section_aliases)
        if not section or section in result:
            continue
        table = _table_after(heading)
        if not table:
            continue
        rows = _parse_table(table, column_synonyms)
        if rows:
            result[section] = rows

    return result
