import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
GW = Path(__file__).parent.parent.parent.parent / "ai_pc" / "reasoning_gateway"

def test_tuned_modelfile_reuses_base_system_and_from_gguf():
    base = (GW / "Modelfile.reasoning").read_text(encoding="utf-8")
    tuned = (GW / "Modelfile.reasoning.tuned").read_text(encoding="utf-8")
    assert "You are the local reasoning model for the Contoso KB chatbot." in tuned
    assert tuned.strip().splitlines()[0].startswith("FROM ")   # FROM the tuned GGUF
    assert "temperature 0" in tuned and "seed 42" in tuned

def test_rollback_targets_base_tag():
    rb = (GW / "08_rollback.ps1").read_text(encoding="utf-8")
    assert "qwen2.5:7b-instruct" in rb
