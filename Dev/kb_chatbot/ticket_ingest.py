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

    for c in data.get("comments", []):
        body = c.get("body", "") or ""
        header = c.get("header", "") or ""
        combined = header + " " + body

        # Names from From/To lines in headers
        for m in _FROM_NAME.findall(combined):
            # Add full name + each individual token
            terms.append(m)
            terms.extend(m.split())

        # Display-name<email> patterns — richest source of real names
        for m in _DISPLAY_EMAIL.findall(combined):
            terms.append(m)
            terms.extend(m.split())

        # Greeting/sign-off names in body
        for m in _GREET_NAME.findall(body):
            terms.append(m)
            terms.extend(m.split())

        # cc: Name <...> in header or body
        for m in _CC_NAME.findall(combined):
            terms.append(m)
            terms.extend(m.split())

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


def _resolution_text(data: dict, known: list[str]) -> str:
    """Collect and redact all internal staff comment bodies."""
    parts: list[str] = []
    for c in data.get("comments", []):
        if c.get("type") == "comment" and c.get("author"):
            r = redact(c.get("body", "") or "", known_terms=known)
            if r:
                parts.append(r)
    return "\n".join(parts).strip()


def _problem_text(data: dict, known: list[str]) -> str:
    """Redact the first customer-facing comment as the problem description,
    falling back to the ticket title."""
    for c in data.get("comments", []):
        if c.get("type") != "comment":
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
    """Internal staff who worked the ticket: comment authors + the 'by <user>'
    sender on outbound (sent-to) email headers. Excludes created_by, which is
    often the external requester."""
    names: list[str] = []
    for c in data.get("comments", []):
        if c.get("type") == "comment" and c.get("author"):
            names.append(str(c["author"]))
        header = c.get("header") or ""
        if "sent to" in header.lower():
            m = _BY_SENDER.search(header)
            # The case-sensitive [a-z] lead is intentional (keeps customer
            # CamelCase display names out); guard against header-noise words so
            # "...by email"/"...by the" don't surface as a "handled by" resource.
            if m and m.group(1).lower() not in _STOPWORDS \
                    and m.group(1).lower() not in {"email", "mail", "fax", "phone", "attachment"}:
                names.append(m.group(1))
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
    if not resolution:
        return []

    problem = _problem_text(data, known)
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
    has_images = bool(data.get("attachment_images"))

    body = f"Problem: {problem}\n\nResolution: {resolution}"
    segments = _split_words(body, TICKET_CHUNK_WORDS) or [body]
    title_line = f"Ticket #{ticket_id} — {safe_title}"

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
                "chunk_index": idx,
            },
        ))
    return chunks
