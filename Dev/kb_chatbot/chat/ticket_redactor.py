"""Conservative PII redaction for support-ticket text.

Org policy forbids surfacing customer PII. This strips emails, phone numbers,
known person/org terms, and email/signature boilerplate BEFORE any ticket text
is indexed or shown. When a line still looks like contact/signature noise after
inline redaction, it is dropped. Conservative by design: prefer dropping to leaking."""
from __future__ import annotations
import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")
_URL = re.compile(r"https?://\S+")

# Lines that are pure email/quote/signature boilerplate -> dropped entirely.
_DROP_LINE = re.compile(
    r"^\s*(subject:|to:|cc:|bcc:|from:|sent:|date:|attachment:|"
    r"registered|authorised by|authorized by|privacy policy|"
    r"important this email|confidential|view our|connect on linkedin|"
    r"t:|e:|w:|tel:|phone:|mobile:|fax:)",
    re.IGNORECASE,
)


def redact(text: str, *, known_terms: list[str]) -> str:
    """Return text with PII removed. known_terms (org/person names from the
    ticket's own fields) are removed case-insensitively as whole words."""
    if not text:
        return ""
    term_res = [
        re.compile(rf"\b{re.escape(t)}\b", re.IGNORECASE)
        for t in known_terms if t and len(t) >= 2
    ]
    cleaned_lines: list[str] = []
    for raw_line in text.replace("\r", "").split("\n"):
        line = raw_line
        if _DROP_LINE.match(line.strip()):
            continue
        line = _EMAIL.sub("[redacted]", line)
        line = _URL.sub("[link]", line)
        line = _PHONE.sub("[redacted]", line)
        for tr in term_res:
            line = tr.sub("[redacted]", line)
        stripped = line.strip()
        if not stripped:
            continue
        cleaned_lines.append(line)
    out = "\n".join(cleaned_lines)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()
