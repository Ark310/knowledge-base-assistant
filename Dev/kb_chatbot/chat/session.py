"""Per-conversation state. Serialisable. No I/O at import time."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4


@dataclass
class Turn:
    role: str
    content: str
    kind: str = "answer"
    citations: list[dict] = field(default_factory=list)
    retrieved_ids: list[str] = field(default_factory=list)
    model: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    ts: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Session:
    id: str
    turns: list[dict] = field(default_factory=list)

    @classmethod
    def new(cls) -> "Session":
        return cls(id=datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:4])

    def add_user(self, msg: str) -> None:
        self.turns.append(Turn(role="user", content=msg, kind="user").to_dict())

    def add(self, turn: Turn) -> None:
        self.turns.append(turn.to_dict())

    def history_for_llm(self, max_turns: int = 6) -> list[dict]:
        kept = self.turns[-max_turns * 2 :] if max_turns > 0 else []
        return [{"role": t["role"], "content": t["content"]} for t in kept if t["role"] in ("user", "assistant")]

    def save(self, dir_path: Path) -> Path:
        dir_path.mkdir(parents=True, exist_ok=True)
        path = dir_path / f"{self.id}.json"
        path.write_text(json.dumps({"id": self.id, "turns": self.turns}, indent=2), encoding="utf-8")
        return path
