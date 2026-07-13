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


def test_format_normalizes_dict_chat_template():
    # Newer transformers' apply_chat_template(tokenize=True) returns a DICT, not a list.
    # format_for_trainer must normalize it to a flat id list and still mask the prompt.
    # (Runs without the GPU libs — format_for_trainer takes the tokenizer as an arg.)
    from Dev.kb_chatbot.finetune.train_qlora import format_for_trainer

    class _FakeTok:
        def apply_chat_template(self, msgs, tokenize=True, add_generation_prompt=False):
            n = 5 if add_generation_prompt else 8   # prompt_only(5) shorter than full(8)
            return {"input_ids": list(range(n)), "attention_mask": [1] * n}

    out = format_for_trainer(
        {"messages": [{"role": "user", "content": "u"}, {"role": "assistant", "content": "a"}]},
        _FakeTok())
    assert out["input_ids"] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert out["labels"][:5] == [-100] * 5   # prompt tokens masked
    assert out["labels"][5:] == [5, 6, 7]    # assistant tokens supervised
    assert len(out["attention_mask"]) == 8
