import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune.build_dataset import assemble

def _rec(ans):
    return {"messages":[{"role":"system","content":"s"},
                        {"role":"user","content":"USER QUESTION:\nq"},
                        {"role":"assistant","content":ans}]}

def test_assemble_splits_holdout_and_is_deterministic():
    recs = [_rec(f"a{i}") for i in range(20)]
    tr1, ev1 = assemble(recs, [], [], holdout=5)
    tr2, ev2 = assemble(recs, [], [], holdout=5)
    assert len(ev1) == 5 and len(tr1) == 15
    assert [m["messages"][2]["content"] for m in ev1] == [m["messages"][2]["content"] for m in ev2]

def test_assemble_scrubs_pii_from_output():
    train, ev = assemble([_rec("mail me at bob@acme.com")], [], [], holdout=0)
    out = train[0]["messages"][2]["content"]
    assert "bob@acme.com" not in out and "[redacted]" in out
