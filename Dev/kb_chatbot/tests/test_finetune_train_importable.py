import sys, importlib.util, pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

def test_train_module_exposes_symbols():
    if importlib.util.find_spec("peft") is None:
        pytest.skip("peft not installed in this env (trainer runs on the AI PC)")
    from Dev.kb_chatbot.finetune import train_qlora as t
    assert hasattr(t, "build_lora_config") and hasattr(t, "format_for_trainer") and hasattr(t, "main")

def test_format_masks_prompt(monkeypatch):
    if importlib.util.find_spec("peft") is None:
        pytest.skip("heavy deps absent")
    from Dev.kb_chatbot.finetune import train_qlora as t
    from transformers import AutoTokenizer
    from Dev.kb_chatbot.finetune import finetune_config as fc
    tok = AutoTokenizer.from_pretrained(fc.BASE_MODEL_HF)
    ex = {"messages":[{"role":"system","content":"s"},{"role":"user","content":"u"},{"role":"assistant","content":"a"}]}
    out = t.format_for_trainer(ex, tok)
    assert set(out) >= {"input_ids","labels"}
    assert any(l == -100 for l in out["labels"])   # prompt tokens masked
    assert any(l != -100 for l in out["labels"])   # assistant tokens kept
