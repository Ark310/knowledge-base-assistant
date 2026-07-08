"""Deterministic per-query classification: product(s), issue-type, referenced ids.

Deterministic by design (pure regex + the config product-synonym map): the same
query always produces the same class, so it always takes the same retrieval path
-> consistent answers."""
from __future__ import annotations
import re
from dataclasses import dataclass, field

from Dev.kb_chatbot import config

ISSUE_ERROR = "error"
ISSUE_HOWTO = "how_to"
ISSUE_CONFIG = "config"
ISSUE_INCIDENT = "incident"
ISSUE_GENERAL = "general"

# Same error vocabulary the orchestrator has used since v2.9.2 (kept in sync).
_ERROR_RE = re.compile(
    r"\b(error|errors|issue|issues|fail(?:s|ed|ing|ure)?|null|exception|crash(?:e[ds])?|"
    r"bug|broken|wrong|incorrect|discrepan\w*|duplicat\w*|missing|not working|doesn'?t|"
    r"cannot|can'?t|unable)\b", re.IGNORECASE)
_INCIDENT_RE = re.compile(r"\bincidents?\b", re.IGNORECASE)
_HOWTO_RE = re.compile(
    r"\b(how (?:do|to|can|would)|steps?|guide|walk ?through|set ?up|configure|"
    r"create|add|enable|book|post)\b", re.IGNORECASE)
_CONFIG_RE = re.compile(
    r"\b(config\w*|settings?|install\w*|permission|enable|disable|toggle)\b", re.IGNORECASE)
# Explicit references only: ticket/bug/incident/# + number (bare numbers collide with amounts).
_TICKET_ID_RE = re.compile(r"(?:ticket|tickets|bug|incident|#)\s*#?\s*(\d{3,7})", re.IGNORECASE)


@dataclass
class QueryClass:
    products: list[str] = field(default_factory=list)
    issue_type: str = ISSUE_GENERAL
    ticket_ids: list[str] = field(default_factory=list)
    is_error: bool = False


def _products(text: str) -> list[str]:
    low = (text or "").lower()
    found: list[str] = []
    for name in config.PRODUCT_SYNONYM_NAMES:
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            slug = config.resolve_product(name)
            if slug and slug not in found:
                found.append(slug)
    return found


def _ticket_ids(text: str) -> list[str]:
    out: list[str] = []
    for m in _TICKET_ID_RE.finditer(text or ""):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def classify(query: str) -> QueryClass:
    q = query or ""
    is_error = bool(_ERROR_RE.search(q))
    if _INCIDENT_RE.search(q):
        issue = ISSUE_INCIDENT
    elif is_error:
        issue = ISSUE_ERROR
    elif _HOWTO_RE.search(q):
        issue = ISSUE_HOWTO
    elif _CONFIG_RE.search(q):
        issue = ISSUE_CONFIG
    else:
        issue = ISSUE_GENERAL
    return QueryClass(products=_products(q), issue_type=issue,
                      ticket_ids=_ticket_ids(q), is_error=is_error)
