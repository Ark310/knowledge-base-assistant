"""Persisted settings (JSON). V2.3 adds learn_mode_hash for Learn Mode password gating.
V2.2 has no API key — Claude Code subprocess uses its own OAuth."""
from __future__ import annotations
import hashlib
import hmac
import json
import os
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
    model_explicitly_set: bool = False
    default_provider: str = "claude"
    reasoning_base_url: str = ""
    reasoning_username: str = ""


_PBKDF2_ITERS = 200_000


def hash_password(password: str) -> str:
    """Salted PBKDF2-HMAC-SHA256. Returns 'pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>'."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERS)
    return f"pbkdf2_sha256${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def check_learn_password(candidate: str, stored_hash: str) -> bool:
    """Verify a Learn-Mode password against the stored hash. Supports the new
    salted PBKDF2 format and the legacy bare-SHA-256 hash (backward compat).
    Constant-time comparison via hmac.compare_digest."""
    if not candidate or not stored_hash:
        return False
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iters_s, salt_hex, hash_hex = stored_hash.split("$")
            dk = hashlib.pbkdf2_hmac("sha256", candidate.encode(),
                                     bytes.fromhex(salt_hex), int(iters_s))
            return hmac.compare_digest(dk.hex(), hash_hex)
        except (ValueError, TypeError):
            return False
    # Legacy bare SHA-256 (so existing installs aren't locked out)
    return hmac.compare_digest(hashlib.sha256(candidate.encode()).hexdigest(), stored_hash)


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
    s = Settings(
        library_path=Path(data.get("library_path", str(defaults.library_path))),
        default_model=data.get("default_model", defaults.default_model),
        confidence_floor=float(data.get("confidence_floor", defaults.confidence_floor)),
        learn_mode_hash=data.get("learn_mode_hash", DEFAULT_LEARN_MODE_HASH),
        model_explicitly_set=bool(data.get("model_explicitly_set", False)),
        default_provider=data.get("default_provider", config.DEFAULT_PROVIDER),
        reasoning_base_url=data.get("reasoning_base_url", ""),
        reasoning_username=data.get("reasoning_username", ""),
    )
    # Guard against a corrupt/hand-edited model/provider mismatch.
    if config.provider_of_model(s.default_model) != s.default_provider:
        s.default_model = config.default_model_for(s.default_provider)
    return s


def save_settings(settings: Settings, path: Path = config.SETTINGS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**asdict(settings), "library_path": str(settings.library_path)}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


_OLD_HAIKU_DEFAULT = "claude-haiku-4-5-20251001"


def migrate_default_model(settings: Settings) -> bool:
    """One-time upgrade: implicit Haiku default -> current (Sonnet) default.
    Returns True if the model was changed (caller announces + persists)."""
    if settings.model_explicitly_set:
        return False
    if settings.default_model != _OLD_HAIKU_DEFAULT:
        return False
    settings.default_model = config.DEFAULT_MODEL
    return True
