import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
import pytest
from Dev.kb_chatbot.finetune import build_dataset as bd

def test_ticket_target_appends_citation():
    t = bd.ticket_target("do the fix", "54000", "https://s/tickets/54000/edit")
    assert "do the fix" in t and "Ticket #54000" in t and "https://s/tickets/54000/edit" in t

def test_abstain_text_matches_prompt_rule():
    assert "don't have enough information" in bd.ABSTAIN_TEXT.lower()

def test_abstain_examples_use_refusal_target():
    class _R:  # retriever stub: no chunks -> abstain scenario
        def retrieve(self, q, f, top_k_rerank=None):
            class RR: chunks = []
            return RR()
    ex = list(bd.abstain_examples(_R(), ["totally unknown question"]))
    assert ex and ex[0]["messages"][2]["content"] == bd.ABSTAIN_TEXT

def test_ticket_examples_question_is_clean_problem_not_metadata(tmp_path):
    import json
    class _R:
        def retrieve(self, q, f, top_k_rerank=None):
            class RR: chunks = []
            return RR()
    (tmp_path / "ticket_54000.json").write_text(json.dumps({
        "ticket_id": "54000", "url": "https://s/tickets/54000/edit", "title": "buy amount",
        "comments": [{"internal": False, "body": "GetWebDeal returns null buy amount"},
                     {"internal": True, "body": "patched the deal calc"}],
        "resolution": {"text": "deploy build 4.2"}}), encoding="utf-8")
    exs = list(bd.ticket_examples(_R(), tmp_path, limit=5))
    assert len(exs) == 1
    user = exs[0]["messages"][1]["content"]
    asst = exs[0]["messages"][2]["content"]
    assert "USER QUESTION:\nGetWebDeal returns null buy amount" in user
    assert "Ticket #54000" not in user and "Date:" not in user   # no metadata leaked into the question
    assert "deploy build 4.2" in asst
    assert "[Ticket #54000](https://s/tickets/54000/edit)" in asst
