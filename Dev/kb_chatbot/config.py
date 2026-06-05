"""V2.2 static defaults + freeze-aware paths. No persisted settings live here."""
from __future__ import annotations
from pathlib import Path
import sys

# ── Freeze-aware base paths ───────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent              # dist/ at runtime
    STATE_DIR = BASE_DIR / "chatbot_state"
else:
    BASE_DIR = Path(__file__).parent.parent.parent      # Knowledge Base/
    STATE_DIR = Path(__file__).parent / "state"

LIBRARY_DEFAULT = BASE_DIR / "library" / "kb"
CHROMA_DIR      = STATE_DIR / "chroma"
CHATS_DIR       = STATE_DIR / "chats"
LOG_FILE        = STATE_DIR / "run.log"
USAGE_FILE      = STATE_DIR / "usage.jsonl"
SETTINGS_FILE   = STATE_DIR / "settings.json"

# ── Bundled data (synonyms etc.) ──────────────────────────────────────────────
if getattr(sys, "frozen", False):
    DATA_DIR = Path(getattr(sys, "_MEIPASS", ".")) / "kb_chatbot_data"
else:
    DATA_DIR = Path(__file__).parent / "data"
SYNONYMS_FILE = DATA_DIR / "synonyms.yaml"

# ── Model defaults ────────────────────────────────────────────────────────────
EMBED_MODEL    = "sentence-transformers/all-MiniLM-L6-v2"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

DEFAULT_MODEL  = "claude-haiku-4-5-20251001"
AVAILABLE_MODELS = {
    "Haiku (fast / cheap)": "claude-haiku-4-5-20251001",
    "Sonnet (smarter)":     "claude-sonnet-4-6",
}

# ── Products (six) ────────────────────────────────────────────────────────────
PRODUCTS = ("api", "tradedesk", "saleshub", "web2", "web4", "other")
PRODUCT_DISPLAY = {
    "api": "API", "tradedesk": "TradeDesk", "saleshub": "SalesHub",
    "web2": "Web2", "web4": "Web4", "other": "Other",
}

# ── Retrieval defaults ────────────────────────────────────────────────────────
TOP_K_RETRIEVE      = 30
TOP_K_RERANK        = 8
CONFIDENCE_FLOOR    = 0.30
CLARIFY_SCORE_FLOOR = -5.0
MAX_HISTORY_TURNS   = 6
CHUNK_TARGET_WORDS  = 500

# ── Cost estimation (USD per million tokens) ──────────────────────────────────
# Used by llm.base.estimate_cost. Claude Code subprocess doesn't bill per-call,
# but tokens-in/out are surfaced and estimate_cost provides a rough USD estimate
# kept for parity with the API path.
COST_TABLE: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
    "claude-sonnet-4-6":         {"in": 3.00, "out": 15.00},
}
