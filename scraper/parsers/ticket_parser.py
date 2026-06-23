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
# The header text is "comment {id} posted by " — the author name is a SEPARATE
# <a> link that follows (confirmed live 2026-06-23), so we capture only the id here.
_COMMENT_HDR_RE = re.compile(r"comment\s+(\d+)\s+posted by", re.I)
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


def _is_download_control(el: Tag) -> bool:
    """True for a Download affordance — a button/anchor whose text OR title is 'Download'.

    Confirmed live 2026-06-23: the files panel uses an ICON button with
    title="Download" (empty text); comment attachments use a text "Download" button.
    The portal renders the title value wrapped in literal quotes, so strip them.
    """
    if not isinstance(el, Tag) or el.name not in ("button", "a"):
        return False
    if _clean(el.get_text()).lower() == "download":
        return True
    return (el.get("title") or "").strip().strip('"').strip().lower() == "download"


def _file_card(el: Tag) -> Tag | None:
    """Nearest ancestor div that looks like a file/attachment card (rounded-lg)."""
    return el.find_parent("div", class_=lambda c: bool(c) and "rounded-lg" in c)


def _filename_text(scope: Tag | None) -> str:
    """Best-effort filename text inside a file card (the break-words/text-sm line)."""
    if scope is None:
        return ""
    for sel in ("p.break-words", "p.text-sm", "h4", ".filename"):
        e = scope.select_one(sel)
        if e and _clean(e.get_text()):
            return _clean(e.get_text())
    mn = scope.select_one("div.min-w-0")
    return _clean(mn.get_text()) if mn else ""


def _data_images(scope: Tag | None) -> list[dict]:
    """Extract inline base64 images (`<img src="data:...;base64,...">`) from a comment body.

    Confirmed live 2026-06-23: comment screenshots embed as data-URI <img> inside
    div.comment-html-content (~230KB each). Returns [{mime, data}] — raw base64; the
    writer decodes it to a file so the base64 never lands in the JSON.
    """
    out = []
    if scope is None:
        return out
    for im in scope.find_all("img"):
        src = im.get("src", "")
        if src.startswith("data:") and ";base64," in src:
            try:
                meta, b64 = src.split(",", 1)
                mime = meta.split(":", 1)[1].split(";", 1)[0]
                out.append({"mime": mime, "data": b64})
            except (ValueError, IndexError):
                pass
    return out


def _attachments_in(scope: Tag) -> list[dict]:
    """Find Download affordances inside *scope* and return their filenames."""
    out = []
    for b in scope.find_all(["button", "a"]):
        if not _is_download_control(b):
            continue
        holder = _file_card(b) or b.find_parent("div", class_="mt-3") or scope
        out.append({"label": _filename_text(holder)})
    return out


# A comment card is the nearest rounded-lg/border/bg-white ancestor of its header.
_COMMENT_CARD_CLASSES = {"rounded-lg", "border", "bg-white"}


def _climb_to_card(node) -> Tag | None:
    """Climb to the nearest ancestor div carrying all of _COMMENT_CARD_CLASSES.

    Done by walking `.parent` and reading `get('class')` (the LIST) — NOT via a
    `class_=` lambda, because BeautifulSoup hands a class filter function the
    space-joined STRING, which silently breaks a multi-class subset test.
    """
    p = node if isinstance(node, Tag) else node.parent
    while isinstance(p, Tag):
        if _COMMENT_CARD_CLASSES <= set(p.get("class") or []):
            return p
        p = p.parent
    return None


def _comment_cards(soup: BeautifulSoup) -> list[Tag]:
    """Each comment is a `div.(p-2 sm:p-4) rounded-lg border bg-white` holding a
    "comment N posted by " header. Anchor on the header text, climb to that card."""
    cards: list[Tag] = []
    seen: set[int] = set()
    for s in soup.find_all(string=_COMMENT_HDR_RE):
        card = _climb_to_card(s.parent)
        if card is not None and id(card) not in seen:
            seen.add(id(card))
            cards.append(card)
    return cards


def parse_comments(html: str) -> list[dict]:
    """Extract all comment cards from the ticket detail page."""
    soup = _soup(html)
    comments = []
    for card in _comment_cards(soup):
        hsn = card.find(string=_COMMENT_HDR_RE)
        if hsn is None:
            continue
        cid = _COMMENT_HDR_RE.search(hsn).group(1)

        # Author is the <a> link that follows "posted by " (the real DOM splits the
        # name out of the header span). Constrain it to this card.
        a = hsn.find_next("a")
        author = _clean(a.get_text()) if (a is not None and card in a.parents) else ""

        # Body is the rendered comment HTML block (NOT the header/meta rows).
        body_el = card.select_one("div.comment-html-content") or card.select_one("div.max-w-none")
        if body_el is not None:
            body = "\n".join(ln.strip() for ln in body_el.get_text("\n").splitlines() if ln.strip())
        else:
            body = ""

        text = card.get_text(" ", strip=True)
        dm = _DATE_RE.search(text)
        # internal=True only when an exact-text "Internal" badge exists in the card —
        # NOT when body prose happens to contain the word "internal".
        internal = any(
            _clean(el.get_text()) == "Internal"
            for el in card.find_all(["span", "div"])
        )
        comments.append({
            "id": cid,
            "author": author,
            "date": dm.group(1) if dm else "",
            "internal": internal,
            "body": body,
            "attachments": _attachments_in(card),
            "images": _data_images(body_el),
        })
    return comments


def parse_resolution(html: str) -> dict:
    """Extract resolution text + attachments from the Resolve sub-view.

    Confirmed live 2026-06-23: scoped to div.resolution-container; the rendered
    resolution text is div.post-content (NOT div.ql-editor — that is the empty edit
    form). Attachments are Download affordances within the panel.
    """
    soup = _soup(html)
    region = soup.select_one("div.resolution-container")
    if region is None:
        return {"text": "", "attachments": []}
    content = region.select_one("div.post-content")
    text = _clean(content.get_text(" ")) if content else ""
    return {"text": text, "attachments": _attachments_in(region)}


def parse_files(html: str) -> list[dict]:
    """Extract the files panel's entries from the Files sub-view.

    Confirmed live 2026-06-23: each file is a card with the filename in a
    p.break-words/p.text-sm and an ICON Download button (title='Download'). We target
    the icon downloads specifically so we capture the panel's authoritative aggregated
    list — not the comment text-Download buttons rendered alongside.
    """
    soup = _soup(html)
    files = []
    for b in soup.find_all("button"):
        if (b.get("title") or "").strip().strip('"').strip().lower() != "download":
            continue
        label = _filename_text(_file_card(b))
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
