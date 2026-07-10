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
