"""Build PII-redacted retrieval chunks from support tickets.

Each ticket yields at most one chunk: title + redacted problem + redacted
resolution. Tickets with no usable internal resolution are skipped. The chunk's
`url` metadata is the resolution_url so the existing citation validator works
unchanged. Supplies comprehensive known_terms (org + usernames + names parsed
from greetings, email From-headers, To/Cc headers, and display-name<email>
patterns) to the redactor."""
from __future__ import annotations
import hashlib
import re
from datetime import datetime

from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.chat.ticket_redactor import redact
from Dev.kb_chatbot import config

TICKET_CHUNK_WORDS = 350  # retrieval window kept below embed (~256) / rerank (~512) truncation


def _parse_created_at(raw: str) -> str:
    """Parse a ticket created_at like '2024-08-22 6:37 AM' to an ISO date 'YYYY-MM-DD'.
    Returns '' on empty/unparseable input (never raises)."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # last resort: leading YYYY-MM-DD token
    import re as _re
    m = _re.match(r"\d{4}-\d{2}-\d{2}", raw)
    return m.group(0) if m else ""


def _split_words(text: str, size: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    if len(words) <= size:
        return [text.strip()]
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


# "received from Sam Rivera" / "sent to Priya Patel" in header strings.
# Keywords are case-insensitive via inline flag; name class is case-SENSITIVE so
# lowercase prose words (e.g. "the outgoing wire template" after "from") are never
# captured as person names.
_FROM_NAME = re.compile(
    r"(?i:received from|sent to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})"
)

# Display-name<email> or "Name <email>" patterns in header/body text.
# e.g. "Priya Patel <priya.patel@foo.com>", "Alex Morgan Chen <alex.chen@foo.com>".
# Name class is case-SENSITIVE: requires leading capital, so lowercase prefixes
# like "sent to" are never included in the captured name.
_DISPLAY_EMAIL = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\s*<[\w.+-]+@[\w.-]+"
    r">"
)

# Greeting/sign-off names from body text (mirrors redactor pattern but used here
# for term extraction). Keyword is case-insensitive via inline flag; name class
# is case-SENSITIVE so "team", "for", "update" etc. are never captured.
_GREET_NAME = re.compile(
    r"\b(?i:Hi|Hello|Dear|Thanks|Thank you|Regards|Cheers|Best|Kind regards|Hey)\b"
    r"[,\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
)

# "cc: Name <email>" style in outbound email headers stored in comments.
# Keyword is case-insensitive via inline flag; name class is case-SENSITIVE.
_CC_NAME = re.compile(
    r"\b(?i:cc):\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\s*[<,]"
)

# Single-token terms whose lowercase form is in this set are never added to the
# redaction list — they are too common to be safe redaction patterns.
_STOPWORDS = {
    "the", "and", "our", "for", "this", "that", "update", "of", "to", "support", "team",
    "please", "thanks", "thank", "you", "with", "from", "is", "are", "was", "were", "in",
    "on", "at", "it", "we", "i", "a", "an", "be", "as", "or", "but", "not", "your", "my",
    "contoso", "customer", "client", "user", "hi", "hello", "dear", "regards", "cheers",
    "now", "me", "let", "get", "sent", "received",
    "could", "would", "should", "also", "however", "therefore", "moreover",
    "additionally", "furthermore", "regarding", "hello",
}


def _known_terms(data: dict) -> list[str]:
    """Collect all person/org names that should be redacted from this ticket."""
    # v2.8: organization is intentionally NOT redacted — this is an internal tool and
    # the client company name is surfaced (also in the structured header). created_by +
    # assignee stay so personal names in the body are still stripped; the surfaced
    # team/client come from _staff_block (fields), not the redacted body.
    terms: list[str] = [
        data.get("created_by", "") or "",
        data.get("assignee", "") or "",
    ]

    def _harvest(text: str) -> None:
        for m in _DISPLAY_EMAIL.findall(text):
            terms.append(m); terms.extend(m.split())
        for m in _FROM_NAME.findall(text):
            terms.append(m); terms.extend(m.split())
        for m in _GREET_NAME.findall(text):
            terms.append(m); terms.extend(m.split())
        for m in _CC_NAME.findall(text):
            terms.append(m); terms.extend(m.split())

    for c in data.get("comments", []) or []:
        # New schema has no per-comment header; harvest the body (tolerate a legacy header).
        _harvest((c.get("header", "") or "") + " " + (c.get("body", "") or ""))
    res = data.get("resolution")
    if isinstance(res, dict):
        _harvest(res.get("text", "") or "")
        for rc in res.get("comments") or []:
            _harvest(rc.get("body", "") or "")

    # De-duplicate, preserve non-empty, case-insensitive uniqueness.
    # Also drop single-token terms that are common stopwords — they must never
    # become redaction patterns or they gut the resolution text.
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        t = t.strip()
        if not t:
            continue
        tl = t.lower()
        if tl in seen:
            continue
        # Drop single tokens (no space) that are in the stopword list
        if " " not in t and tl in _STOPWORDS:
            continue
        # Drop multi-token terms only if ALL tokens are stopwords
        if " " in t and all(tok.lower() in _STOPWORDS for tok in t.split()):
            continue
        seen.add(tl)
        out.append(t)
    return out


def _is_staff_comment(c: dict) -> bool:
    """New schema: internal=True marks a Contoso-internal (staff) note.
    Legacy fallback: type == 'comment'."""
    return bool(c.get("internal")) or c.get("type") == "comment"


def _resolution_text(data: dict, known: list[str]) -> str:
    """Redacted resolution: the Resolve field text + internal staff comment bodies
    + resolution-thread comment bodies."""
    parts: list[str] = []
    res = data.get("resolution")
    if isinstance(res, dict):
        t = redact(res.get("text", "") or "", known_terms=known)
        if t:
            parts.append(t)
        for rc in res.get("comments") or []:
            r = redact(rc.get("body", "") or "", known_terms=known)
            if r:
                parts.append(r)
    for c in data.get("comments") or []:
        if _is_staff_comment(c):
            r = redact(c.get("body", "") or "", known_terms=known)
            if r:
                parts.append(r)
    return "\n".join(parts).strip()


def _problem_text(data: dict, known: list[str]) -> str:
    """First non-staff (customer-facing) comment, redacted; else the ticket title."""
    for c in data.get("comments") or []:
        if not _is_staff_comment(c):
            r = redact(c.get("body", "") or "", known_terms=known)
            if r:
                return r
    return redact(data.get("title", "") or "", known_terms=known)


_BY_SENDER = re.compile(r"\bby\s+([a-z][\w.\-]+)")  # "...sent to <customer> by mlopez"


def _dedupe_keep_order(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        v = (v or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _handled_by(data: dict) -> list[str]:
    """Internal staff who worked the ticket: staff (internal) comment authors +
    resolution-thread comment authors. Excludes created_by (often the requester)."""
    names: list[str] = []
    for c in data.get("comments") or []:
        if _is_staff_comment(c) and c.get("author"):
            names.append(str(c["author"]))
    res = data.get("resolution")
    if isinstance(res, dict):
        for rc in res.get("comments") or []:
            if rc.get("author"):
                names.append(str(rc["author"]))
    created_by = (data.get("created_by") or "").strip().lower()
    return [n for n in _dedupe_keep_order(names) if n.lower() != created_by]


def _staff_block(data: dict) -> str:
    """Field-derived, un-redacted team/client header. Contains only the client
    company name + internal staff usernames — never customer-individual PII."""
    lines: list[str] = []
    org = (data.get("organization") or "").strip()
    if org:
        lines.append(f"Client: {org}")
    parts: list[str] = []
    owner = (data.get("csqa_owner") or "").strip()
    if owner:
        parts.append(f"CSQA owner: {owner}")
    assignee = (data.get("assignee") or "").strip()
    if assignee:
        parts.append(f"Assignee: {assignee}")
    qa = _dedupe_keep_order([data.get("sqa_assignee"), data.get("site1_qa_signoff"),
                             data.get("site2_qa_signoff")])
    if qa:
        parts.append("QA sign-off: " + ", ".join(qa))
    handled = _handled_by(data)
    if handled:
        parts.append("Handled by: " + ", ".join(handled))
    if parts:
        lines.append(" · ".join(parts))
    return "\n".join(lines)


def build_ticket_chunks(data: dict, path) -> list[Chunk]:
    """Return 1..N Chunks for the ticket (split for retrieval; reassembled to the
    full ticket at answer time via ticket_id + chunk_index). Skips tickets with no
    internal resolution comment. Each chunk leads with the ticket title; the
    field-derived staff/client header rides on the first chunk. `has_images` flags
    that the ticket page carries screenshot(s) — the images themselves are never
    indexed, stored, or surfaced."""
    known = _known_terms(data)
    resolution = _resolution_text(data, known)
    problem = _problem_text(data, known)
    resolved = bool(resolution)
    if not resolution and not problem:
        return []  # genuinely nothing to index

    raw_title = data.get("title", "") or f"Ticket {data.get('ticket_id', '')}"
    raw_project = (data.get("product", "") or "").strip()
    product = config.normalize_ticket_product(raw_project)
    created_at = _parse_created_at(data.get("created_at", ""))
    ticket_id = str(data.get("ticket_id", ""))
    ticket_url = data.get("url", "") or data.get("resolution_url", "")
    resolution_url = data.get("resolution_url", "") or data.get("url", "")
    safe_title = redact(raw_title, known_terms=known) or f"Ticket {ticket_id}"
    handled = _handled_by(data)
    header = _staff_block(data)

    def _has_imgs(comments) -> bool:
        return any(c.get("images") for c in (comments or []))
    res = data.get("resolution") if isinstance(data.get("resolution"), dict) else {}
    has_images = bool(data.get("attachment_images")) or _has_imgs(data.get("comments")) \
        or _has_imgs(res.get("comments"))

    resolution_block = resolution if resolved else "(no recorded resolution yet — unresolved)"
    body = f"Problem: {problem}\n\nResolution: {resolution_block}"
    segments = _split_words(body, TICKET_CHUNK_WORDS) or [body]
    marker = "" if resolved else " [UNRESOLVED]"
    title_line = f"Ticket #{ticket_id} — {safe_title}{marker}"

    chunks: list[Chunk] = []
    for idx, seg in enumerate(segments):
        text = title_line
        if idx == 0:
            if created_at:
                text += f"\nDate: {created_at}"
            if header:
                text += "\n" + header
        text += "\n\n" + seg
        cid = "ticket_" + hashlib.sha1(
            f"{ticket_id}:{raw_title}:{idx}".encode()).hexdigest()[:16]
        chunks.append(Chunk(
            id=cid,
            text=text,
            metadata={
                "kind": "ticket",
                "product": product,
                "project": raw_project,
                "created_at": created_at,
                "category": data.get("category", "") or "ticket",
                "title": f"Ticket #{ticket_id}",
                "ticket_id": ticket_id,
                "url": ticket_url,
                "resolution_url": resolution_url,
                "organization": data.get("organization", "") or "",
                "csqa_owner": data.get("csqa_owner", "") or "",
                "assignee": data.get("assignee", "") or "",
                "handled_by": ", ".join(handled),
                "has_images": has_images,
                "resolved": resolved,
                "chunk_index": idx,
            },
        ))
    return chunks
