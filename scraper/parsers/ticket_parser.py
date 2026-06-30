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
# Each thread entry's header text identifies it. A comment reads "comment {id} posted
# by "; an email reads "email {id} received from " (inbound) or "email {id} sent by "
# (outbound). The phrase sits in one text node; the author/sender is a SEPARATE <a> link
# that follows (confirmed live: comments 2026-06-23, emails 2026-06-30 on ticket 70403).
# NB the tradedesk phrasing differs from the legacy contoso portal ("email N sent to X
# by Y") — do not share the legacy _EMAIL_HDR_RE. Emails were previously dropped
# entirely because only the comment header was matched (bug-106).
_COMMENT_HDR_RE = re.compile(r"comment\s+(\d+)\s+posted\s+by", re.I)
_EMAIL_HDR_RE = re.compile(r"email\s+(\d+)\s+(?:received\s+from|sent\s+by)", re.I)
# Combined comment|email matcher: group(1) = comment id, group(2) = email id.
_ENTRY_HDR_RE = re.compile(
    r"comment\s+(\d+)\s+posted\s+by|email\s+(\d+)\s+(?:received\s+from|sent\s+by)", re.I)
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


def _is_download_control(el: Tag, icon_only: bool = False) -> bool:
    """True for a Download affordance — a button/anchor whose text OR title is 'Download'.

    Confirmed live 2026-06-23: the files panel + resolution file use an ICON button with
    title="Download" (empty text, value wrapped in literal quotes); comment attachments
    use a text "Download" button. `icon_only=True` matches ONLY the title/icon variant —
    used by parse_resolution so a comment text-"Download" rendered alongside the resolution
    can never be mis-attributed as a resolution file.
    """
    if not isinstance(el, Tag) or el.name not in ("button", "a"):
        return False
    title_match = (el.get("title") or "").strip().strip('"').strip().lower() == "download"
    if icon_only:
        return title_match
    return title_match or _clean(el.get_text()).lower() == "download"


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


def _attachments_in(scope: Tag, icon_only: bool = False) -> list[dict]:
    """Find Download affordances inside *scope* and return their filenames."""
    out = []
    for b in scope.find_all(["button", "a"]):
        if not _is_download_control(b, icon_only):
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
    """Each thread entry (comment OR email) is a `div.(p-2 sm:p-4) rounded-lg border
    bg-white` holding a "comment N posted by " / "email N received from " / "email N
    sent by " header. Anchor on the header text, climb to that card. Each live entry
    has its OWN card (confirmed on 70403: 7 entries → 7 cards), so dedup by card."""
    cards: list[Tag] = []
    seen: set[int] = set()
    for s in soup.find_all(string=_ENTRY_HDR_RE):
        card = _climb_to_card(s.parent)
        if card is not None and id(card) not in seen:
            seen.add(id(card))
            cards.append(card)
    return cards


def _card_to_comment(card: Tag) -> dict | None:
    """Parse one thread-entry card (comment or email) into the canonical comment dict
    (or None if no header). Emails carry the same shape; author = sender."""
    hsn = card.find(string=_ENTRY_HDR_RE)
    if hsn is None:
        return None
    m = _ENTRY_HDR_RE.search(hsn)
    cid = m.group(1) or m.group(2)

    # Author is the <a> link that follows the header phrase (the real DOM splits the
    # name/sender out of the header span). Constrain it to this card.
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
    return {
        "id": cid,
        "author": author,
        "date": dm.group(1) if dm else "",
        "internal": internal,
        "body": body,
        "attachments": _attachments_in(card),
        "images": _data_images(body_el),
    }


def _comments_in(scope) -> list[dict]:
    """Parse every comment card found within `scope` (a BeautifulSoup doc or a Tag)."""
    out: list[dict] = []
    for card in _comment_cards(scope):
        c = _card_to_comment(card)
        if c is not None:
            out.append(c)
    return out


def parse_comments(html: str) -> list[dict]:
    """Extract all comment cards from the ticket detail page."""
    return _comments_in(_soup(html))


def parse_resolution(html: str) -> dict:
    """Extract resolution text + its own comment thread + attachments from the Resolve
    sub-view.

    Confirmed live 2026-06-23: scoped to div.resolution-container; the rendered
    resolution text is div.post-content (NOT div.ql-editor — that is the empty edit
    form). Attachments are Download affordances within the panel. A resolution can
    also carry a comment THREAD (same card markup as ticket comments) — captured here
    scoped to the container so the main ticket comments are never double-counted.
    """
    soup = _soup(html)
    region = soup.select_one("div.resolution-container")
    if region is None:
        return {"text": "", "comments": [], "attachments": []}
    content = region.select_one("div.post-content")
    text = _clean(content.get_text(" ")) if content else ""
    # icon_only: the resolution file is an icon button[title="Download"]; never count a
    # comment's text-"Download" that may be rendered alongside the resolution panel.
    return {
        "text": text,
        "comments": _comments_in(region),
        "attachments": _attachments_in(region, icon_only=True),
    }


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
