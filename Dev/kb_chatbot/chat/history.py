"""Chat history persistence for the web UI.

One JSON file per chat under CHATS_DIR (now off OneDrive): {id, title, ts, turns}.
Storage-only + decoupled from Session (callers pass/receive the turns list), so it
is fully unit-testable without any GUI/engine. Auto-titles a chat by the ticket #
it references, else the first user question."""
from __future__ import annotations
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from Dev.kb_chatbot import config

_TICKET_RE = re.compile(r"(?:ticket|tickets|bug|incident|#)\s*#?\s*(\d{3,7})", re.IGNORECASE)
_MAX_TITLE = 60


def _dir(chats_dir=None) -> Path:
    d = Path(chats_dir) if chats_dir is not None else Path(config.CHATS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _first_user_text(turns: list[dict]) -> str:
    for t in turns or []:
        if t.get("role") == "user" and (t.get("content") or "").strip():
            return t["content"].strip()
    return ""


def auto_title(turns: list[dict]) -> str:
    """Ticket # if any user turn references one, else the first user question
    (trimmed), else 'New chat'."""
    for t in turns or []:
        if t.get("role") != "user":
            continue
        m = _TICKET_RE.search(t.get("content", "") or "")
        if m:
            return f"Ticket #{m.group(1)}"
    first = _first_user_text(turns)
    if not first:
        return "New chat"
    first = " ".join(first.split())
    return first if len(first) <= _MAX_TITLE else first[:_MAX_TITLE - 1].rstrip() + "…"


def _new_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:4]


def save_chat(turns: list[dict], chat_id: Optional[str] = None,
              title: Optional[str] = None, chats_dir=None) -> str:
    d = _dir(chats_dir)
    cid = chat_id or _new_id()
    existing = {}
    fp = d / f"{cid}.json"
    if fp.exists():
        try:
            existing = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    payload = {
        "id": cid,
        "title": title or existing.get("title") or auto_title(turns),
        "ts": datetime.now().isoformat(timespec="seconds"),
        "turns": turns or [],
    }
    fp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return cid


def load_chat(chat_id: str, chats_dir=None) -> Optional[dict]:
    fp = _dir(chats_dir) / f"{chat_id}.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_chats(chats_dir=None) -> list[dict]:
    d = _dir(chats_dir)
    out = []
    for fp in d.glob("*.json"):
        try:
            c = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({"id": c.get("id", fp.stem), "title": c.get("title", fp.stem),
                    "ts": c.get("ts", "")})
    out.sort(key=lambda c: c["ts"], reverse=True)
    return out


def rename_chat(chat_id: str, title: str, chats_dir=None) -> bool:
    c = load_chat(chat_id, chats_dir)
    if c is None:
        return False
    c["title"] = title
    (_dir(chats_dir) / f"{chat_id}.json").write_text(
        json.dumps(c, ensure_ascii=False), encoding="utf-8")
    return True


def delete_chat(chat_id: str, chats_dir=None) -> bool:
    fp = _dir(chats_dir) / f"{chat_id}.json"
    if fp.exists():
        fp.unlink()
        return True
    return False


def search_chats(query: str, chats_dir=None) -> list[dict]:
    q = (query or "").strip().lower()
    if not q:
        return list_chats(chats_dir)
    d = _dir(chats_dir)
    hits = []
    for fp in d.glob("*.json"):
        try:
            c = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        hay = (c.get("title", "") + " " +
               " ".join(str(t.get("content", "")) for t in c.get("turns", []))).lower()
        if q in hay:
            hits.append({"id": c.get("id", fp.stem), "title": c.get("title", fp.stem),
                         "ts": c.get("ts", "")})
    hits.sort(key=lambda c: c["ts"], reverse=True)
    return hits
