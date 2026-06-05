import json
import tempfile
from pathlib import Path

from Dev.kb_chatbot.usage_stats import load_usage, summarize, cost_for, UsageSummary


HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"


def _rec(ts, kind="answer", model=HAIKU, tin=1000, tout=100):
    return {"ts": ts, "kind": kind, "model": model, "tokens_in": tin, "tokens_out": tout}


def _write(path, records, garbage_line=False):
    lines = [json.dumps(r) for r in records]
    if garbage_line:
        lines.insert(1, "{not valid json")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_cost_for_haiku():
    # 1M in @ $1 + 1M out @ $5
    assert cost_for({"model": HAIKU, "tokens_in": 1_000_000, "tokens_out": 1_000_000}) == 6.0


def test_cost_for_sonnet():
    assert cost_for({"model": SONNET, "tokens_in": 1_000_000, "tokens_out": 1_000_000}) == 18.0


def test_cost_for_unknown_model_is_zero():
    assert cost_for({"model": "mystery-model", "tokens_in": 999, "tokens_out": 999}) == 0.0


def test_cost_for_missing_model_is_zero():
    assert cost_for({"tokens_in": 100, "tokens_out": 100}) == 0.0


def test_cost_for_null_tokens_is_zero_not_crash():
    # JSON null values come through as None — must not TypeError
    assert cost_for({"model": HAIKU, "tokens_in": None, "tokens_out": None}) == 0.0


def test_load_skips_malformed_lines():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "usage.jsonl"
        _write(p, [_rec("2026-06-05T10:00:00"), _rec("2026-06-05T10:01:00")], garbage_line=True)
        assert len(load_usage(p)) == 2


def test_load_missing_file_returns_empty():
    assert load_usage(Path("does/not/exist.jsonl")) == []


def test_load_excludes_failed_auth_records():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "usage.jsonl"
        _write(p, [_rec("2026-06-05T10:00:00"),
                   {"kind": "learn_mode_failed_auth", "ts": "2026-06-05T10:02:00"}])
        records = load_usage(p)
        assert len(records) == 1


def test_summarize_splits_session_window():
    records = [
        _rec("2026-06-05T09:00:00", tin=2000, tout=200),   # before session
        _rec("2026-06-05T11:00:00", tin=1000, tout=100),   # in session
        _rec("2026-06-05T11:05:00", kind="rewrite", tin=300, tout=30),  # in session
    ]
    s = summarize(records, session_start="2026-06-05T10:30:00")
    assert s.total_in == 3300 and s.total_out == 330
    assert s.session_in == 1300 and s.session_out == 130
    assert s.total_queries == 3 and s.session_queries == 2
    assert s.total_cost > s.session_cost > 0


def test_summarize_zero_token_rows_not_counted_as_queries():
    records = [
        _rec("2026-06-05T11:00:00"),
        {"ts": "2026-06-05T11:01:00", "kind": "clarification", "model": None,
         "tokens_in": 0, "tokens_out": 0},
    ]
    s = summarize(records, session_start="2026-06-05T10:00:00")
    assert s.total_queries == 1


def test_summarize_empty():
    s = summarize([], session_start="2026-06-05T10:00:00")
    assert s == UsageSummary(0, 0, 0.0, 0, 0, 0, 0.0, 0)
