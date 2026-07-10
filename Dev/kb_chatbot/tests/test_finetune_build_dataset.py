import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
import pytest
from Dev.kb_chatbot.finetune import build_dataset as bd

def test_split_problem_resolution():
    p, r = bd.split_problem_resolution("Problem: buy amount null\n\nResolution: patch getdeal")
    assert p == "buy amount null" and r == "patch getdeal"

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
