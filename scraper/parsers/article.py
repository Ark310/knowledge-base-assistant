# scraper/parsers/article.py
from __future__ import annotations
from datetime import datetime
from bs4 import BeautifulSoup, Tag, NavigableString

from scraper.parsers.universal import _find_content, _collapse_ws
from scraper.config import BASE_URL


def _abs_url(src: str) -> str:
    return src if src.startswith("http") else f"{BASE_URL}{src}"


def _inline_content(el: Tag) -> str:
    """Extract inline-formatted text from an element."""
    parts: list[str] = []
    for child in el.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif child.name in ("strong", "b"):
            t = child.get_text()
            parts.append(f"**{t}**" if t.strip() else t)
        elif child.name in ("em", "i"):
            t = child.get_text()
            parts.append(f"*{t}*" if t.strip() else t)
        elif child.name == "code":
            parts.append(f"`{child.get_text()}`")
        elif child.name == "a":
            text = _collapse_ws(child.get_text())
            href = child.get("href", "")
            parts.append(f"[{text}]({href})" if href and not href.startswith("#") else text)
        elif child.name == "img":
            alt = child.get("alt", "image")
            src = child.get("src", "")
            parts.append(f"![{alt}]({_abs_url(src)})" if src else "")
        elif child.name == "br":
            parts.append("\n")
        elif hasattr(child, "children"):
            parts.append(_inline_content(child))
        else:
            parts.append(str(child))
    return _collapse_ws("".join(parts))


def _table_to_md(table: Tag) -> str:
    """Convert HTML table to Markdown table."""
    rows = table.find_all("tr")
    if not rows:
        return ""
    headers = [_collapse_ws(c.get_text(separator=" ", strip=True))
               for c in rows[0].find_all(["th", "td"])]
    if not headers:
        return ""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for tr in rows[1:]:
        cells = tr.find_all(["td", "th"])
        vals = [_collapse_ws(c.get_text(separator=" ", strip=True)) for c in cells]
        while len(vals) < len(headers):
            vals.append("")
        lines.append("| " + " | ".join(vals[: len(headers)]) + " |")
    return "\n".join(lines)


def _element_to_md(el: Tag, list_depth: int = 0) -> str:
    """Recursively convert a BeautifulSoup element to a Markdown string."""
    if isinstance(el, NavigableString):
        return str(el).strip()

    name = el.name
    if not name or name in ("script", "style"):
        return ""

    classes: list[str] = el.get("class") or []

    # Skip table-of-contents macros
    if "toc-macro" in classes:
        return ""
    if name == "div" and el.get("data-macro-name") == "toc":
        return ""

    # Headings
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        text = _collapse_ws(el.get_text(separator=" ", strip=True))
        return f"\n{'#' * int(name[1])} {text}\n" if text else ""

    # Paragraphs
    if name == "p":
        text = _inline_content(el)
        return f"\n{text}\n" if text.strip() else ""

    # Ordered / unordered lists
    if name in ("ul", "ol"):
        parts: list[str] = []
        counter = 0
        for child in el.children:
            if not isinstance(child, Tag) or child.name != "li":
                continue
            counter += 1
            prefix = f"{counter}." if name == "ol" else "-"
            indent = "  " * list_depth
            direct: list[str] = []
            nested = ""
            for li_child in child.children:
                if isinstance(li_child, NavigableString):
                    direct.append(str(li_child))
                elif li_child.name in ("ul", "ol"):
                    nested += "\n" + _element_to_md(li_child, list_depth + 1)
                else:
                    direct.append(_inline_content(li_child))
            item_text = _collapse_ws("".join(direct))
            parts.append(f"{indent}{prefix} {item_text}{nested}")
        return "\n" + "\n".join(parts) + "\n"

    # Tables
    if name == "table":
        return "\n" + _table_to_md(el) + "\n"

    # Code blocks
    if name == "pre":
        code_el = el.find("code")
        code = code_el.get_text() if code_el else el.get_text()
        return f"\n```\n{code}\n```\n"

    if name == "code" and (not el.parent or el.parent.name != "pre"):
        return f"`{el.get_text()}`"

    # Images
    if name == "img":
        alt = el.get("alt", "image")
        src = el.get("src", "")
        return f"![{alt}]({_abs_url(src)})" if src else ""

    # Confluence info / note / warning / tip panels
    if "confluence-information-macro" in classes:
        body_div = el.find("div", class_="confluence-information-macro-body")
        note_text = _inline_content(body_div) if body_div else el.get_text(strip=True)
        note_type = "Note"
        for cls in classes:
            if "warning" in cls:
                note_type = "Warning"
                break
            if "tip" in cls:
                note_type = "Tip"
                break
        return f"\n> **{note_type}:** {note_text}\n"

    # Confluence expand macro — render contents
    if "expand-container" in classes or el.get("data-macro-name") == "expand":
        body = el.find("div", class_="expand-content") or el
        inner = [_element_to_md(c, list_depth) for c in body.children if isinstance(c, Tag)]
        return "\n".join(p for p in inner if p.strip())

    # Blockquote
    if name == "blockquote":
        inner_parts = [_element_to_md(c, list_depth) for c in el.children if isinstance(c, Tag)]
        inner = "\n".join(p for p in inner_parts if p.strip())
        return "\n" + "\n".join(f"> {line}" for line in inner.splitlines()) + "\n"

    # Generic container — recurse
    child_parts: list[str] = []
    for child in el.children:
        if isinstance(child, NavigableString):
            t = str(child).strip()
            if t:
                child_parts.append(t)
        elif isinstance(child, Tag):
            md = _element_to_md(child, list_depth)
            if md.strip():
                child_parts.append(md)

    sep = " " if name in ("span", "td", "th") else "\n"
    return sep.join(child_parts)


def parse_article(
    html: str,
    space_key: str,
    space_name: str,
    product: str,
    title: str,
    url: str,
    screenshot_path: str,
) -> dict:
    """Parse a rendered Confluence page HTML into an article data dict."""
    soup = BeautifulSoup(html, "lxml")

    for sel in (".toc-macro", "[data-macro-name='toc']", "#breadcrumbs", ".page-metadata"):
        for node in soup.select(sel):
            node.decompose()

    content = _find_content(soup)

    parts: list[str] = []
    for child in content.children:
        if isinstance(child, NavigableString):
            t = str(child).strip()
            if t:
                parts.append(t)
        elif isinstance(child, Tag):
            md = _element_to_md(child)
            if md.strip():
                parts.append(md.strip())

    return {
        "space_key": space_key,
        "space_name": space_name,
        "product": product,
        "title": title,
        "url": url,
        "scraped_at": datetime.now().isoformat(),
        "screenshot": screenshot_path,
        "body_md": "\n\n".join(parts),
    }
