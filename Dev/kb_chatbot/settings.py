"""Persisted settings (JSON). V2.3 adds learn_mode_hash for Learn Mode password gating.
V2.2 has no API key — Claude Code subprocess uses its own OAuth."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path

from Dev.kb_chatbot import config

# Default password hash: SHA-256 of the Learn Mode password. The plaintext is
# never stored — only this hash is persisted and compared against.
_DEFAULT_LEARN_PASSWORD = "YOUR_LEARN_PASSWORD_HERE"
DEFAULT_LEARN_MODE_HASH = hashlib.sha256(_DEFAULT_LEARN_PASSWORD.encode()).hexdigest()


@dataclass
class Settings:
    library_path: Path
    default_model: str
    confidence_floor: float
    learn_mode_hash: str = field(default_factory=lambda: DEFAULT_LEARN_MODE_HASH)


def check_learn_password(candidate: str, stored_hash: str) -> bool:
    """Compare SHA-256 hash of candidate against stored_hash."""
    if not candidate:
        return False
    return hashlib.sha256(candidate.encode()).hexdigest() == stored_hash


def load_settings(path: Path = config.SETTINGS_FILE) -> Settings:
    defaults = Settings(
        library_path=config.LIBRARY_DEFAULT,
        default_model=config.DEFAULT_MODEL,
        confidence_floor=config.CONFIDENCE_FLOOR,
    )
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    return Settings(
        library_path=Path(data.get("library_path", str(defaults.library_path))),
        default_model=data.get("default_model", defaults.default_model),
        confidence_floor=float(data.get("confidence_floor", defaults.confidence_floor)),
        learn_mode_hash=data.get("learn_mode_hash", DEFAULT_LEARN_MODE_HASH),
    )


def save_settings(settings: Settings, path: Path = config.SETTINGS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**asdict(settings), "library_path": str(settings.library_path)}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
