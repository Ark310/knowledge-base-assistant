"""PII/secret gate for the training set. find_leaks scans for REAL emails, phone
numbers, secret keys, and passwords — NOT the '[redacted]' placeholders the ticket
redactor already inserts. scrub() neutralizes any match to '[redacted]' (so benign
business emails in KB context don't block the build); assert_clean() is the backstop
verifier that raises if anything PII-shaped survives."""
from __future__ import annotations
import re

class LeakError(RuntimeError):
    pass

# Real email (not a bare '[redacted]' token).
_EMAIL  = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# NANP phone shapes with separators (416-555-0134, (416) 555-0134, 416.555.0134,
# +1 416 555 0134). Deliberately NOT bare 10-digit runs (avoids flagging IDs), and
# not ISO dates (2024-08-22 has a 4-2-2 shape that never matches area+prefix+line).
_PHONE = re.compile(
    r"(?<!\d)(?:\+?\d{1,2}[\s.\-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.\-])\d{3}[\s.\-]\d{4}(?!\d)")
# Common secret-key shapes (Anthropic, OpenAI, AWS, generic bearer).
_SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9\-]{16,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{10,}|gh[pousr]_[A-Za-z0-9]{20,})\b")
_PASSWORD = re.compile(r"(?i)\bpassword\s*[:=]\s*(?!\[redacted\])\S+")

_CATS = (("email", _EMAIL), ("phone", _PHONE), ("secret", _SECRET), ("password", _PASSWORD))

def find_leaks(text: str) -> list[str]:
    t = text or ""
    return [cat for cat, rx in _CATS if rx.search(t)]

def scan_records(records: list[dict]) -> list[tuple[int, str, str]]:
    hits = []
    for i, rec in enumerate(records):
        for msg in rec.get("messages", []):
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            for cat in find_leaks(content):
                hits.append((i, cat, content[:80]))
    return hits

def assert_clean(records: list[dict]) -> None:
    hits = scan_records(records)
    if hits:
        raise LeakError(f"{len(hits)} PII/secret leak(s) in training data; "
                        f"first: example {hits[0][0]} [{hits[0][1]}] {hits[0][2]!r}")


_REPLACEMENT = "[redacted]"

def scrub(text: str) -> str:
    """Replace any email / phone / secret / password value with [redacted].
    Neutralizes benign business emails (e.g. user@contoso.example) that ride in KB
    context so they don't block the build, while removing any real PII too."""
    if not text:
        return text
    for _cat, rx in _CATS:
        text = rx.sub(_REPLACEMENT, text)
    return text

def scrub_records(records: list[dict]) -> list[dict]:
    """Scrub every string message content in place; returns the same list."""
    for rec in records:
        for msg in rec.get("messages", []):
            c = msg.get("content")
            if isinstance(c, str):
                msg["content"] = scrub(c)
    return records
