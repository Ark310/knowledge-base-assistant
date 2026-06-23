"""Parse ticket detail and resolution pages from portal.contoso.example.

The support portal is a JS SPA whose API is end-to-end encrypted.
All parsing operates on the rendered DOM only — no network, no browser.

Ticket detail:  {portal}/tickets/{ticket_id}/edit
Resolution:     Resolve sub-view (same URL, different rendered content)
Files:          Files sub-view

Selectors confirmed against synthetic fixtures 2026-06-22.
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def _clean(t) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


_LABEL_MAP: dict[str, str] = {
    "organization": "organization",
    "project": "product",
    "priority": "priority",
    "category": "category",
    "severity": "severity",
    "status": "status",
    "assigned to": "assignee",
    "csqa owner": "csqa_owner",
}

_TICKET_NO_RE = re.compile(r"Ticket\s*#\s*(\d+)", re.I)
_CREATED_RE = re.compile(r"Created\s+(\d{2}/\d{2}/\d{4})\s+by\s+(\S+)", re.I)
_COMMENT_HDR_RE = re.compile(r"comment\s+(\d+)\s+posted by\s+(.+?)\s*$", re.I)
_DATE_RE = re.compile(r"([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s*[AP]M)")


def is_not_found(html: str, ticket_id: str = "") -> bool:
    """True when the portal page is NOT a ticket detail (redirected to /bugs list)."""
    soup = _soup(html)
    if soup.select_one("button.floating-dropdown-btn"):
        return False
    return not _TICKET_NO_RE.search(soup.get_text(" ", strip=True))


def parse_ticket_fields(html: str) -> dict:
    """Extract metadata fields, ticket id, title, created-at/by, and checkbox state."""
    soup = _soup(html)
    out: dict = {}

    for btn in soup.select("button.floating-dropdown-btn"):
        lab = btn.select_one(".floating-dropdown-label")
        val = btn.select_one(".floating-dropdown-value")
        if not lab or not val:
            continue
        # Strip trailing asterisk (the required-field star is a child span)
        label_text = _clean(lab.get_text()).rstrip("*").strip().lower()
        key = _LABEL_MAP.get(label_text)
        if not key or key in out:
            continue
        v = _clean(val.get_text())
        if v:
            out[key] = v

    full = soup.get_text(" ", strip=True)

    m = _TICKET_NO_RE.search(full)
    if m:
        out["ticket_id"] = m.group(1)

    if soup.title and soup.title.string:
        mt = re.match(r"Ticket ID \d+ -\s*(.+)$", _clean(soup.title.string))
        if mt:
            out["title"] = mt.group(1).strip()

    mc = _CREATED_RE.search(full)
    if mc:
        out["created_at"] = mc.group(1)
        out["created_by"] = mc.group(2)

    chk = soup.find("input", attrs={"type": "checkbox"})
    out["awaiting_production_deployment"] = bool(chk and chk.has_attr("checked"))

    return out


def _comment_cards(soup: BeautifulSoup) -> list[Tag]:
    """Return every div.p-2 card inside the comments container."""
    for s in soup.select("span.hidden"):
        if _COMMENT_HDR_RE.search(s.get_text()):
            container = s.find_parent("div", class_="space-y-2")
            if container:
                return container.find_all("div", class_="p-2", recursive=False)
    return []


def _attachments_in(scope: Tag) -> list[dict]:
    """Find all Download buttons inside *scope* and return their filenames."""
    out = []
    for b in scope.find_all("button"):
        if _clean(b.get_text()).lower() != "download":
            continue
        # Look for the filename in the nearest mt-3 ancestor, then flex, then scope
        holder = (
            b.find_parent("div", class_="mt-3")
            or b.find_parent("div", class_="flex")
            or scope
        )
        fn = holder.select_one(".filename") or holder.select_one(".min-w-0")
        out.append({"label": _clean(fn.get_text()) if fn else ""})
    return out


def parse_comments(html: str) -> list[dict]:
    """Extract all comment cards from the ticket detail page."""
    soup = _soup(html)
    comments = []
    for card in _comment_cards(soup):
        hdr = None
        for s in card.select("span.hidden"):
            m = _COMMENT_HDR_RE.search(_clean(s.get_text()))
            if m:
                hdr = m
                break
        if not hdr:
            continue

        text = card.get_text(" ", strip=True)
        dm = _DATE_RE.search(text)
        body = "\n".join(
            _clean(p.get_text())
            for p in card.find_all("p")
            if _clean(p.get_text())
        )
        comments.append({
            "id": hdr.group(1),
            "author": _clean(hdr.group(2)),
            "date": dm.group(1) if dm else "",
            "internal": "internal" in text.lower(),
            "body": body,
            "attachments": _attachments_in(card),
        })
    return comments


def parse_resolution(html: str) -> dict:
    """Extract resolution text and attachments from the Resolve sub-view.

    Returns {"text": str, "attachments": [{"label": str}]}.
    Scoped strictly to div.resolution-container to avoid picking up comment
    download buttons rendered below the resolution panel.
    """
    soup = _soup(html)
    region = soup.select_one("div.resolution-container") or soup
    editor = region.select_one("div.ql-editor")
    text = "\n".join(
        _clean(p.get_text())
        for p in (editor.find_all("p") if editor else [])
        if _clean(p.get_text())
    )
    return {"text": text, "attachments": _attachments_in(region)}


def parse_files(html: str) -> list[dict]:
    """Extract all file entries from the Files sub-view.

    Returns [{"label": str}] — one entry per Download button, label is the
    filename text from the adjacent div.min-w-0 / .filename element.
    """
    soup = _soup(html)
    files = []
    for b in soup.find_all("button"):
        if _clean(b.get_text()).lower() != "download":
            continue
        card = (
            b.find_parent("div", class_="border-2")
            or b.find_parent("div", class_="flex")
        )
        fn = (card.select_one(".filename") or card.select_one("div.min-w-0")) if card else None
        label = _clean(fn.get_text()) if fn else ""
        label = re.sub(r"\bDownload\b", "", label).strip()
        if label:
            files.append({"label": label})
    return files


def parse_ticket_detail(html: str, ticket_id: str, portal_url: str) -> dict:
    """Orchestrate field + comment extraction into a single ticket dict.

    Returns {} when the page is not a ticket detail (not-found redirect).
    """
    if is_not_found(html, ticket_id):
        return {}

    data = parse_ticket_fields(html)
    data["ticket_id"] = data.get("ticket_id") or ticket_id
    data["comments"] = parse_comments(html)
    base = portal_url.rstrip("/")
    data["url"] = f"{base}/tickets/{ticket_id}/edit"
    data["scraped_at"] = datetime.now().isoformat()
    return data
