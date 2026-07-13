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


def test_format_encodes_via_text_and_masks_prompt():
    # format_for_trainer must render the template to TEXT (tokenize=False) then tokenize,
    # producing INT ids (never char strings), and mask the prompt portion.
    # Runs without the GPU libs — the tokenizer is passed in.
    from Dev.kb_chatbot.finetune.train_qlora import format_for_trainer

    class _FakeTok:
        def apply_chat_template(self, msgs, tokenize=False, add_generation_prompt=False):
            # rendered TEXT; the assistant answer is only present in the full render
            return "PROMPT" if add_generation_prompt else "PROMPTANSWER"
        def __call__(self, text, add_special_tokens=False):
            return {"input_ids": [ord(c) for c in text]}   # crude char-level ids (ints)

    out = format_for_trainer(
        {"messages": [{"role": "user", "content": "u"}, {"role": "assistant", "content": "a"}]},
        _FakeTok())
    assert out["input_ids"] == [ord(c) for c in "PROMPTANSWER"]
    assert all(isinstance(x, int) for x in out["input_ids"])   # ints, NOT char strings
    assert out["labels"][:6] == [-100] * 6                     # "PROMPT" masked
    assert out["labels"][6:] == [ord(c) for c in "ANSWER"]     # "ANSWER" supervised
