"""Hard PII/secret gate for the training set. find_leaks scans for REAL emails,
phone numbers, secret keys, and passwords — NOT the '[redacted]' placeholders the
ticket redactor already inserts. assert_clean fails the build if anything leaks."""
from __future__ import annotations
import re

class LeakError(RuntimeError):
    pass

# Real email (not a bare '[redacted]' token).
_EMAIL  = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Phone: 10+ digits with separators; avoids ISO dates (which have no leading +/() and are 8 digits).
_PHONE  = re.compile(r"(?<!\d)(?:\+?\d[\s().\-]?){10,}\d(?!\d)")
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
