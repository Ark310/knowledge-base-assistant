"""V2.8 static defaults + freeze-aware paths + provider registry + tickets. No persisted settings live here."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import os
import shutil
import sys

# Single source of truth for the app version. Surfaced in the window title and
# the exe filename (read by ContosoKBChatbot.spec). Bump here only.
APP_VERSION = "2.9.2"

# ── Freeze-aware base paths ───────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent.parent.parent      # Knowledge Base/

# Live state lives OFF OneDrive (cloud-sync corrupts live SQLite / Chroma).
_LOCALAPPDATA = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
STATE_DIR = Path(_LOCALAPPDATA) / "ContosoKBChatbot"

# Legacy state locations that predate the move (migrated once on startup).
_LEGACY_STATE = (BASE_DIR / "chatbot_state") if getattr(sys, "frozen", False) \
    else (Path(__file__).parent / "state")

LIBRARY_DEFAULT = BASE_DIR / "library" / "kb"
TICKETS_DEFAULT = BASE_DIR / "library" / "tickets"
CHROMA_DIR      = STATE_DIR / "chroma"
CHATS_DIR       = STATE_DIR / "chats"
LOG_FILE        = STATE_DIR / "run.log"
USAGE_FILE      = STATE_DIR / "usage.jsonl"
SETTINGS_FILE   = STATE_DIR / "settings.json"


def migrate_state_if_needed(old) -> bool:
    """One-time copy of a pre-existing legacy state dir into STATE_DIR. Returns
    True if a copy happened, False if skipped (no legacy dir, or new already set up)."""
    old = Path(old)
    if not old.exists():
        return False
    if STATE_DIR.exists() and any(STATE_DIR.iterdir()):
        return False
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for child in old.iterdir():
        dest = STATE_DIR / child.name
        try:
            if child.is_dir():
                shutil.copytree(child, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(child, dest)
        except Exception:
            pass
    return True

# ── Model defaults ────────────────────────────────────────────────────────────
EMBED_MODEL    = "sentence-transformers/all-MiniLM-L6-v2"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
LOCAL_MODEL    = "contoso-reasoning-qwen25-7b"   # on-prem model served via the AI-PC gateway

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
        # v2.9.1: with model_reasoning_effort pinned to "low" (codex_provider), the
        # Codex CLI no longer rejects gpt-5.4-mini (the earlier 400 was the high/
        # default-effort + injected-tool combo). gpt-5.4 stays default for accuracy;
        # mini is offered as a faster/cheaper option.
        "default_model": "gpt-5.4",
        "models": {
            "GPT-5.4": "gpt-5.4",
            "GPT-5.4-mini (fast / cheap)": "gpt-5.4-mini",
        },
    },
    "local": {
        "display": "Local (on-prem)",
        "default_model": "contoso-reasoning-qwen25-7b",
        "models": {
            "Contoso Reasoning (Qwen2.5-7B)": "contoso-reasoning-qwen25-7b",
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
    "contoso-reasoning-qwen25-7b": "Contoso Reasoning",
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

# ── Products (seven) ─────────────────────────────────────────────────────────
PRODUCTS = ("api", "tradedesk", "saleshub", "formflow", "web2", "web4", "other")
PRODUCT_DISPLAY = {
    "api": "API", "tradedesk": "TradeDesk", "saleshub": "SalesHub",
    "formflow": "FormFlow", "web2": "Web2", "web4": "Web4", "other": "Other",
}

# FormFlow (standalone) == FormFlow (legacy, embedded in TradeDesk/others) — one
# forms product. SalesHub is separate.
_PRODUCT_SYNONYMS = {
    "formflow": "formflow", "formflow": "formflow",
    "formflow": "formflow", "formflow": "formflow",
    "saleshub": "saleshub", "saleshub": "saleshub",
    "tradedesk": "tradedesk", "td": "tradedesk",
    "web2": "web2", "web4": "web4", "api": "api", "other": "other",
}


def resolve_product(name: str) -> Optional[str]:
    """Map a product name/synonym typed by a user to a canonical slug, or None."""
    return _PRODUCT_SYNONYMS.get((name or "").strip().lower())


# Every user-typable product name/synonym (incl. no-space "formflow" and "td").
# Single source of truth so orchestrator product-detection can't drift from resolve_product.
PRODUCT_SYNONYM_NAMES = tuple(_PRODUCT_SYNONYMS)


# Raw ticket "Project" value -> canonical product slug (tickets store rich Project
# names that don't match KB slugs). Unknown -> "other"; raw value kept separately.
_TICKET_PROJECT_MAP = {
    "td client server": "tradedesk", "business modeling": "tradedesk",
    "td web api": "api", "rest api": "api",
    "td web portal v4.0": "web4",
    "td web portal v2.0": "web2", "td web portal v1": "web2",
    "formflow": "formflow", "saleshub": "saleshub",
}


def normalize_ticket_product(raw: str) -> str:
    return _TICKET_PROJECT_MAP.get((raw or "").strip().lower(), "other")

# ── Retrieval defaults ────────────────────────────────────────────────────────
TOP_K_RETRIEVE        = 30
TOP_K_RERANK          = 8
TOP_K_RERANK_ERROR    = 14   # wider rerank window for error/issue questions
CONFIDENCE_FLOOR    = 0.06   # sigmoid(rerank logit); was 0.30 on raw logits (over-abstained)
OUT_OF_SCOPE_FLOOR  = 0.02   # below this rerank score the query is treated as outside the KB scope
CLARIFY_SCORE_FLOOR = 0.0    # rerank score is now 0-1; 0.0 keeps the abstain-path clarify check live
MAX_HISTORY_TURNS   = 6
CHUNK_TARGET_WORDS  = 500
ANSWER_MAX_TOKENS   = 2048   # full ticket resolutions can exceed 1024; completeness wins (v2.9.1)

# ── Hybrid retrieval (BM25 keyword + vector, fused via RRF) ─────────────────────
HYBRID_ENABLED = True
BM25_TOP_K     = 30    # keyword candidates fused with the vector candidates
RRF_K          = 60    # Reciprocal Rank Fusion damping constant

# ── Answer cache (identical answer for a repeated standalone question) ──────────
ANSWER_CACHE_ENABLED = True
ANSWER_CACHE_FILE    = STATE_DIR / "answer_cache.json"
ANSWER_CACHE_MAX     = 2000
# Cache auto-invalidates when the corpus/embedder version changes. Bump the prefix
# if the corpus is rebuilt with new chunking.
INDEX_VERSION        = f"v4:{EMBED_MODEL}"

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
    "contoso-reasoning-qwen25-7b": {"in": 0.0, "out": 0.0},   # on-prem, no per-token cost
}
