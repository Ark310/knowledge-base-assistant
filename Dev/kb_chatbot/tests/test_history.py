import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat import history as H


def _turns(*pairs):
    out = []
    for role, content in pairs:
        out.append({"role": role, "content": content})
    return out


def test_auto_title_prefers_ticket_number():
    turns = _turns(("user", "why does ticket 75919 fail?"), ("assistant", "..."))
    assert H.auto_title(turns) == "Ticket #75919"


def test_auto_title_falls_back_to_first_question():
    turns = _turns(("user", "How do I book a spot deal in TradeDesk?"))
    assert H.auto_title(turns) == "How do I book a spot deal in TradeDesk?"


def test_auto_title_trims_long_question():
    long_q = "please explain " * 20
    t = H.auto_title(_turns(("user", long_q)))
    assert len(t) <= 60 and t.endswith("…")


def test_auto_title_empty():
    assert H.auto_title([]) == "New chat"


def test_save_list_load_roundtrip(tmp_path):
    turns = _turns(("user", "ticket 54000 margin issue"), ("assistant", "fixed"))
    cid = H.save_chat(turns, chats_dir=tmp_path)
    listed = H.list_chats(chats_dir=tmp_path)
    assert len(listed) == 1 and listed[0]["id"] == cid
    assert listed[0]["title"] == "Ticket #54000"
    loaded = H.load_chat(cid, chats_dir=tmp_path)
    assert loaded["turns"] == turns


def test_save_updates_existing_id(tmp_path):
    cid = H.save_chat(_turns(("user", "first")), chats_dir=tmp_path)
    H.save_chat(_turns(("user", "first"), ("assistant", "a")), chat_id=cid, chats_dir=tmp_path)
    assert len(H.list_chats(chats_dir=tmp_path)) == 1  # same file, not a new one


def test_rename(tmp_path):
    cid = H.save_chat(_turns(("user", "x")), chats_dir=tmp_path)
    assert H.rename_chat(cid, "My renamed chat", chats_dir=tmp_path) is True
    assert H.load_chat(cid, chats_dir=tmp_path)["title"] == "My renamed chat"
    assert H.rename_chat("nope", "t", chats_dir=tmp_path) is False


def test_delete(tmp_path):
    cid = H.save_chat(_turns(("user", "x")), chats_dir=tmp_path)
    assert H.delete_chat(cid, chats_dir=tmp_path) is True
    assert H.load_chat(cid, chats_dir=tmp_path) is None
    assert H.delete_chat(cid, chats_dir=tmp_path) is False


def test_search(tmp_path):
    H.save_chat(_turns(("user", "drawdown margin duplication")), chats_dir=tmp_path)
    H.save_chat(_turns(("user", "how to configure holidays")), chats_dir=tmp_path)
    hits = H.search_chats("margin", chats_dir=tmp_path)
    assert len(hits) == 1
    assert H.search_chats("", chats_dir=tmp_path) == H.list_chats(chats_dir=tmp_path)
    assert H.search_chats("nonexistent-term", chats_dir=tmp_path) == []
