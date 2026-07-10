import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from Dev.kb_chatbot.finetune.eval_compare import abstain_safety, passes_gate

def test_abstain_safety_counts_refusals():
    good = ["I don't have enough information in the knowledge base to answer this confidently.", ""]
    bad  = ["Sure, the fix is to reboot."]
    assert abstain_safety(good) == 1.0
    assert abstain_safety(good + bad) < 1.0

def test_gate_requires_quality_up_and_safety_not_down():
    base  = {"accuracy": 0.60, "abstain_safety": 0.90}
    good  = {"accuracy": 0.72, "abstain_safety": 0.92}
    worse_safety = {"accuracy": 0.80, "abstain_safety": 0.80}
    assert passes_gate(good, base)[0] is True
    assert passes_gate(worse_safety, base)[0] is False

def test_abstain_safety_recognizes_all_refusal_phrasings():
    from Dev.kb_chatbot.finetune.eval_compare import abstain_safety
    assert abstain_safety(["That's outside the scope of the Contoso knowledge base."]) == 1.0
    assert abstain_safety(["I haven't been trained on this - it's not in the knowledge base."]) == 1.0

def test_eval_fixtures_present_and_parseable():
    from pathlib import Path
    from Dev.kb_chatbot.eval.dataset import load
    base = Path(__file__).parent.parent / "finetune"
    cases = load(base / "eval_holdout.json")
    assert len(cases) >= 5 and all(c.question for c in cases)
    unsup = [q for q in (base / "unsupported_questions.txt").read_text(encoding="utf-8").splitlines() if q.strip()]
    assert len(unsup) >= 5
