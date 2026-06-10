"""V2.6 static defaults + freeze-aware paths + provider registry + tickets. No persisted settings live here."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import sys

# ── Freeze-aware base paths ───────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent              # dist/ at runtime
    STATE_DIR = BASE_DIR / "chatbot_state"
else:
    BASE_DIR = Path(__file__).parent.parent.parent      # Knowledge Base/
    STATE_DIR = Path(__file__).parent / "state"

LIBRARY_DEFAULT = BASE_DIR / "library" / "kb"
TICKETS_DEFAULT = BASE_DIR / "library" / "tickets"
CHROMA_DIR      = STATE_DIR / "chroma"
CHATS_DIR       = STATE_DIR / "chats"
LOG_FILE        = STATE_DIR / "run.log"
USAGE_FILE      = STATE_DIR / "usage.jsonl"
SETTINGS_FILE   = STATE_DIR / "settings.json"

# ── Model defaults ────────────────────────────────────────────────────────────
EMBED_MODEL    = "sentence-transformers/all-MiniLM-L6-v2"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

DEFAULT_PROVIDER = "claude"

PROVIDERS = {
    "claude": {
        "display": "Claude",
        "default_model": "claude-sonnet-4-6",
        "models": {
            "Haiku (fast / cheap)": "claude-haiku-4-5-20251001",
            "Sonnet (smarter)":     "claude-sonnet-4-6",
        },
    },
    "openai": {
        "display": "ChatGPT",
        "default_model": "gpt-5.5",
        "models": {
            "GPT-5.5 (smartest)":  "gpt-5.5",
            "GPT-5.4 (mid)":       "gpt-5.4",
            "GPT-5.4-mini (fast)": "gpt-5.4-mini",
        },
    },
}

# Backward-compatible aliases (Claude provider) so existing imports keep working
DEFAULT_MODEL    = PROVIDERS["claude"]["default_model"]
AVAILABLE_MODELS = PROVIDERS["claude"]["models"]

MODEL_DISPLAY = {
    "claude-haiku-4-5-20251001": "Haiku",
    "claude-sonnet-4-6":         "Sonnet",
    "gpt-5.5":                   "GPT-5.5",
    "gpt-5.4":                   "GPT-5.4",
    "gpt-5.4-mini":              "GPT-5.4-mini",
}


def models_for(provider_id: str) -> dict:
    return PROVIDERS.get(provider_id, PROVIDERS[DEFAULT_PROVIDER])["models"]


def default_model_for(provider_id: str) -> str:
    return PROVIDERS.get(provider_id, PROVIDERS[DEFAULT_PROVIDER])["default_model"]


def provider_of_model(model_id: str) -> Optional[str]:
    for pid, prov in PROVIDERS.items():
        if model_id in prov["models"].values():
            return pid
    return None

# ── Products (six) ────────────────────────────────────────────────────────────
PRODUCTS = ("api", "tradedesk", "saleshub", "web2", "web4", "other")
PRODUCT_DISPLAY = {
    "api": "API", "tradedesk": "TradeDesk", "saleshub": "SalesHub",
    "web2": "Web2", "web4": "Web4", "other": "Other",
}

# ── Retrieval defaults ────────────────────────────────────────────────────────
TOP_K_RETRIEVE      = 30
TOP_K_RERANK        = 8
CONFIDENCE_FLOOR    = 0.06   # sigmoid(rerank logit); was 0.30 on raw logits (over-abstained)
CLARIFY_SCORE_FLOOR = 0.0    # rerank score is now 0-1; 0.0 keeps the abstain-path clarify check live
MAX_HISTORY_TURNS   = 6
CHUNK_TARGET_WORDS  = 500

# ── Cost estimation (USD per million tokens) ──────────────────────────────────
# Used by llm.base.estimate_cost. Claude Code subprocess doesn't bill per-call,
# but tokens-in/out are surfaced and estimate_cost provides a rough USD estimate
# kept for parity with the API path.
COST_TABLE: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
    "claude-sonnet-4-6":         {"in": 3.00, "out": 15.00},
    "gpt-5.5":                   {"in": 5.00, "out": 30.00},
    "gpt-5.4":                   {"in": 2.50, "out": 15.00},
    "gpt-5.4-mini":              {"in": 0.75, "out": 4.50},
}
