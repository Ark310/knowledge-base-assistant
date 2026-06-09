"""V2.2 static defaults + freeze-aware paths. No persisted settings live here."""
from __future__ import annotations
from pathlib import Path
import sys

# ── Version / beta identity ───────────────────────────────────────────────────
APP_VERSION = "3.0.0-beta"
IS_BETA     = True
# Beta uses a separate state dir so it never touches the stable exe's index.
STATE_DIR_NAME = "chatbot_state_beta" if IS_BETA else "chatbot_state"


def window_title() -> str:
    return "Contoso KB Chatbot — v3.0 BETA" if IS_BETA else "Contoso KB Chatbot"


# ── Freeze-aware base paths ───────────────────────────────────────────────────
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).parent              # dist/ at runtime
    STATE_DIR = BASE_DIR / STATE_DIR_NAME
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
# v3: bge-reranker-base lifted golden-set recall@8 0.816 -> 0.908 vs ms-marco.
# Outputs 0-1 sigmoid scores (not raw logits), so CONFIDENCE_FLOOR is on that scale.
_EMBED_REPO    = "sentence-transformers/all-MiniLM-L6-v2"
_RERANKER_REPO = RERANKER_MODEL_REPO = "BAAI/bge-reranker-base"


def _model_path(repo: str) -> str:
    """Frozen builds bundle model snapshots under <_MEIPASS>/models/<repo-with-dashes>;
    dev runs (and a frozen build missing the bundle) fall back to the HF cache by repo id."""
    if getattr(sys, "frozen", False):
        local = Path(getattr(sys, "_MEIPASS", ".")) / "models" / repo.replace("/", "--")
        if local.exists():
            return str(local)
    return repo


EMBED_MODEL    = _model_path(_EMBED_REPO)
RERANKER_MODEL = _model_path(_RERANKER_REPO)

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
CONFIDENCE_FLOOR    = 0.05          # bge-reranker-base scale; calibrated on golden set
CLARIFY_SCORE_FLOOR = 0.01          # bge sigmoid scale: above pure-gibberish (~0), below vague-query signal
MAX_HISTORY_TURNS   = 6
CHUNK_TARGET_WORDS  = 500
CHUNK_OVERLAP_WORDS = 80            # adopted: golden-set recall@8 0.908->0.920, MRR 0.705->0.760
BM25_FILE           = "bm25.pkl"     # lives inside the chroma dir
HYBRID_BM25         = True           # BM25 + vector with RRF fusion
QUERY_EXPANSION     = True           # synonym expansion on the BM25 query
RRF_K               = 60

# ── Cost estimation (USD per million tokens) ──────────────────────────────────
# Used by llm.base.estimate_cost. Claude Code subprocess doesn't bill per-call,
# but tokens-in/out are surfaced and estimate_cost provides a rough USD estimate
# kept for parity with the API path.
COST_TABLE: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"in": 1.00, "out": 5.00},
    "claude-sonnet-4-6":         {"in": 3.00, "out": 15.00},
}
