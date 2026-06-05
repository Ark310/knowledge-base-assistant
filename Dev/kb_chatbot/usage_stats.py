"""Pure aggregation over state/usage.jsonl for the token usage viewer.

Costs are computed at display time from config.COST_TABLE so editing a rate
reprices all history. No I/O besides reading the jsonl; no network."""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from Dev.kb_chatbot import config

log = logging.getLogger("kb_chatbot.usage_stats")

_EXCLUDED_KINDS = {"learn_mode_failed_auth"}


@dataclass(frozen=True)
class UsageSummary:
    total_in: int
    total_out: int
    total_cost: float
    total_queries: int
    session_in: int
    session_out: int
    session_cost: float
    session_queries: int


def cost_for(record: dict) -> float:
    """API-equivalent USD cost of one usage record. Unknown model -> 0.0."""
    rates = config.COST_TABLE.get(record.get("model") or "")
    if not rates:
        return 0.0
    # `or 0` guards explicit JSON nulls, not just missing keys
    return ((record.get("tokens_in") or 0) * rates["in"]
            + (record.get("tokens_out") or 0) * rates["out"]) / 1_000_000


def load_usage(path: Path) -> list[dict]:
    """All usage records, oldest first. Malformed lines and auth-failure
    records are skipped; a missing file is an empty history."""
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            log.warning("Skipping malformed usage line")
            continue
        if rec.get("kind") in _EXCLUDED_KINDS:
            continue
        records.append(rec)
    return records


def summarize(records: list[dict], *, session_start: str = "") -> UsageSummary:
    """Aggregate totals; ISO-string ts comparison is safe (lexicographic).
    'Queries' counts records that actually consumed tokens."""
    total_in = total_out = total_q = 0
    sess_in = sess_out = sess_q = 0
    total_cost = sess_cost = 0.0
    for r in records:
        tin = r.get("tokens_in", 0) or 0
        tout = r.get("tokens_out", 0) or 0
        cost = cost_for(r)
        total_in += tin
        total_out += tout
        total_cost += cost
        if tin + tout > 0:
            total_q += 1
        if session_start and (r.get("ts") or "") >= session_start:
            sess_in += tin
            sess_out += tout
            sess_cost += cost
            if tin + tout > 0:
                sess_q += 1
    return UsageSummary(total_in, total_out, total_cost, total_q,
                        sess_in, sess_out, sess_cost, sess_q)
