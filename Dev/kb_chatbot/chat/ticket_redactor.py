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

# Names following a greeting/closing word: "Hi Sam", "Dear Sarah", "Thanks Mike",
# "Regards, Jane", "HI Dana", "Regards, Priya Patel".
# Keyword is case-insensitive via inline flag; name class stays case-SENSITIVE so
# lowercase words like "for", "the", "update" are never captured as names.
_GREETING_NAME = re.compile(
    r"\b((?i:Hi|Hello|Dear|Thanks|Thank you|Regards|Cheers|Best|Kind regards|Hey))\b"
    r"([,\s]+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})(?=[\s,.!?]|$)"
)

# Names after action verbs: "Messaged Riley", "asked Priya", "emailed Jane".
# Also handles "the user/customer/client (Name)" variant and multi-token names.
# Verb is case-insensitive via inline flag; name class is case-SENSITIVE.
_ACTION_NAME = re.compile(
    r"\b((?i:messaged|message|asked|told|emailed|email|called|contacted|"
    r"spoke to|spoke with|pinged|notified|informed|advised|reached out to))\s+"
    r"(?:the\s+(?:user|customer|client)\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
)

# Parenthetical first-name mentions: "user (Robin)", "(Dana)".
_PAREN_NAME = re.compile(r"\(([A-Z][a-z]+)\)")

# Credential VALUES after a label ("Password: X", "API Key = Y", "Decrypt key: Z").
# Keeps the keyword (so "reset the password" prose survives), redacts the value.
# Tolerates an optional closing quote between keyword and separator and a quoted
# value, so JSON/query forms like "password": "secret" are also caught.
_CRED_LABEL = re.compile(
    r"(?i)\b(pass(?:word|phrase)?|pwd|user\s?name|username|login|"
    r"api[\s_-]?key|secret(?:\s*key)?|access[\s_-]?key|private[\s_-]?key|"
    r"decrypt\s*key|auth[\s_-]?token|token|credentials?|"
    r"client[\s_-]?id|customer[\s_-]?id|gateway(?:\s*customer)?(?:\s*id)?|"
    r"sk|client[\s_-]?secret|bearer)\b"
    r"""(["']?\s*(?:for[^:=\n]*)?[:=]\s*)"""
    r"""(?:(["'])[^"'\n]*\2|[^\n;,]+)"""
)
# Credential pairs in URL/query form: password=..., pwd=..., secret=..., token=...
_CRED_KV = re.compile(
    r"(?i)\b(pass(?:word)?|pwd|secret|token|api[_-]?key|access[_-]?key|user(?:name)?|login)"
    r"(=)([^\s&]+)"
)
# @mentions of names: @Dana, @Hasan
_AT_MENTION = re.compile(r"@[A-Za-z][\w.\-]*")
# Bare email-domain residue left after local-part redaction.
_BARE_DOMAIN = re.compile(r"@[\w.\-]+\.\w{2,}")

# ── Label-independent secret-shape scrubbing ──────────────────────────────────
# Catches secrets that have no recognised label (OAuth client IDs, raw API keys,
# base64/hex blobs, JWTs, hex wallet addresses). Conservative thresholds so
# version strings, order numbers, and ordinary words are not eaten.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_HEX_ADDR = re.compile(r"\b0x[0-9a-fA-F]{16,}\b")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{20,}")


def _looks_secret(tok: str) -> bool:
    core = tok.strip("=")
    if len(core) < 20:
        return False
    # base64-ish or hex blob of length >= 32
    if len(core) >= 32 and re.fullmatch(r"[A-Za-z0-9+/]+", core):
        return True
    if len(core) >= 32 and re.fullmatch(r"[0-9a-fA-F]+", core):
        return True
    # high-entropy: >= 20 chars mixing lower + upper + digit (looks like a key)
    has_low = any(c.islower() for c in core)
    has_up = any(c.isupper() for c in core)
    has_dig = any(c.isdigit() for c in core)
    return len(core) >= 20 and has_low and has_up and has_dig


def _redact_secret_shapes(line: str) -> str:
    line = _JWT.sub("[redacted]", line)
    line = _HEX_ADDR.sub("[redacted]", line)
    return _LONG_TOKEN.sub(
        lambda m: "[redacted]" if _looks_secret(m.group(0)) else m.group(0), line
    )

# Lines that are pure email/quote/signature boilerplate -> dropped entirely.
_DROP_LINE = re.compile(
    r"^\s*(subject:|to:|cc:|bcc:|from:|sent:|date:|attachment:|"
    r"registered|authorised by|authorized by|privacy policy|"
    r"important this email|confidential|view our|connect on linkedin|"
    r"t:|e:|w:|tel:|phone:|mobile:|fax:)",
    re.IGNORECASE,
)

_SIGNOFF_LINE = re.compile(
    r"^\s*(?i:regards|thanks|thank you|best|kind regards|cheers|sincerely|br|warm regards)\b"
)
_NAME_ONLY_LINE = re.compile(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}$")


def _is_signoff(line: str) -> bool:
    return bool(_SIGNOFF_LINE.match(line.strip()))


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
    prev_signoff = False
    for raw_line in text.replace("\r", "").split("\n"):
        line = raw_line
        stripped_raw = line.strip()
        if _DROP_LINE.match(stripped_raw):
            prev_signoff = _is_signoff(stripped_raw)
            continue
        # A short all-capitalised line right after a sign-off is a signature name.
        if prev_signoff and _NAME_ONLY_LINE.match(stripped_raw):
            prev_signoff = False
            continue
        prev_signoff = _is_signoff(stripped_raw)
        line = _EMAIL.sub("[redacted]", line)
        line = _CRED_KV.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", line)
        line = _CRED_LABEL.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", line)
        line = _redact_secret_shapes(line)
        line = _AT_MENTION.sub("@[redacted]", line)
        line = _BARE_DOMAIN.sub("[redacted]", line)
        line = _URL.sub("[link]", line)
        line = _PHONE.sub("[redacted]", line)
        line = _GREETING_NAME.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", line)
        line = _ACTION_NAME.sub(lambda m: f"{m.group(1)} [redacted]", line)
        line = _PAREN_NAME.sub("([redacted])", line)
        for tr in term_res:
            line = tr.sub("[redacted]", line)
        stripped = line.strip()
        if not stripped:
            continue
        cleaned_lines.append(line)
    out = "\n".join(cleaned_lines)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip()


def scrub_answer(text: str) -> str:
    """Defense-in-depth: strip emails / credential pairs / labelled secrets /
    secret-shaped tokens / phones from an LLM answer before it is shown or
    persisted. Deliberately does NOT run the contextual name patterns or
    known_terms — internal staff usernames and ordinary prose must survive,
    and citations must stay intact."""
    if not text:
        return ""
    out_lines: list[str] = []
    for line in text.replace("\r", "").split("\n"):
        line = _EMAIL.sub("[redacted]", line)
        line = _CRED_KV.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", line)
        line = _CRED_LABEL.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", line)
        line = _redact_secret_shapes(line)
        line = _PHONE.sub("[redacted]", line)
        out_lines.append(line)
    return "\n".join(out_lines)
