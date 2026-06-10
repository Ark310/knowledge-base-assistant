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

from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.chat.ticket_redactor import redact

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
}


def _known_terms(data: dict) -> list[str]:
    """Collect all person/org names that should be redacted from this ticket."""
    terms: list[str] = [
        data.get("organization", "") or "",
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


def build_ticket_chunks(data: dict, path) -> list[Chunk]:
    """Return a list of at most one Chunk for the given ticket dict.

    Skips tickets with no usable internal resolution comment. The chunk url
    metadata equals resolution_url so the existing citation validator works."""
    known = _known_terms(data)
    resolution = _resolution_text(data, known)
    if not resolution:
        return []

    problem = _problem_text(data, known)
    raw_title = data.get("title", "") or f"Ticket {data.get('ticket_id', '')}"
    product = data.get("product", "") or "tickets"
    ticket_id = str(data.get("ticket_id", ""))
    resolution_url = data.get("resolution_url", "") or data.get("url", "")

    # Redact title before embedding into chunk text — titles can contain org names
    safe_title = redact(raw_title, known_terms=known) or f"Ticket {ticket_id}"

    text = (
        f"Ticket #{ticket_id}: {safe_title}\n\n"
        f"Problem: {problem}\n\n"
        f"Resolution: {resolution}"
    )
    cid = "ticket_" + hashlib.sha1(f"{ticket_id}:{raw_title}".encode()).hexdigest()[:16]

    return [Chunk(
        id=cid,
        text=text,
        metadata={
            "kind": "ticket",
            "product": product,
            "category": data.get("category", "") or "ticket",
            "title": f"Ticket #{ticket_id}",
            "ticket_id": ticket_id,
            "url": resolution_url,
            "resolution_url": resolution_url,
            "chunk_index": 0,
        },
    )]
