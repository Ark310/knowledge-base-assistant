"""QLoRA fine-tune Qwen2.5-7B-Instruct on the redaction-gated train.jsonl.
Native Windows: transformers + peft + bitsandbytes (4-bit NF4). Runs on the AI PC
in the dedicated GPU window. `--dry-run` trains 2 steps on <=16 examples to
validate the path + VRAM before the full run."""
from __future__ import annotations
import argparse
import time
from Dev.kb_chatbot.finetune import finetune_config as fc

def build_lora_config():
    from peft import LoraConfig
    return LoraConfig(
        r=fc.LORA_R, lora_alpha=fc.LORA_ALPHA, lora_dropout=fc.LORA_DROPOUT,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    )

def _encode(tokenizer, msgs, add_generation_prompt: bool) -> list:
    """Render the chat template to TEXT (tokenize=False), then tokenize explicitly to
    a flat list of int ids. This avoids apply_chat_template(tokenize=True), whose return
    shape differs across transformers versions (list vs dict vs -- here -- a plain string,
    which list() turned into single-character strings and broke torch.tensor)."""
    text = tokenizer.apply_chat_template(msgs, tokenize=False,
                                         add_generation_prompt=add_generation_prompt)
    return tokenizer(text, add_special_tokens=False)["input_ids"]


def format_for_trainer(example: dict, tokenizer, max_len=None) -> dict:
    """Qwen chat template; supervise ONLY the assistant turn (mask the rest to -100).
    If max_len is set and the example is longer, keep the TAIL -- the answer plus as much
    preceding context/question as fits -- so the supervised answer is never cut; the front
    (system prompt / earliest context) is what's dropped. This keeps every example usable
    on an 8 GB card instead of filtering long ones out entirely."""
    msgs = example["messages"]
    full = _encode(tokenizer, msgs, add_generation_prompt=False)
    prompt_only = _encode(tokenizer, msgs[:-1], add_generation_prompt=True)
    labels = list(full)
    for i in range(min(len(prompt_only), len(labels))):
        labels[i] = -100
    if max_len and len(full) > max_len:
        full = full[-max_len:]
        labels = labels[-max_len:]
    return {"input_ids": list(full), "attention_mask": [1] * len(full), "labels": labels}

def main(argv=None) -> None:
    import torch
    from datasets import load_dataset
    from transformers import (AutoTokenizer, AutoModelForCausalLM,
                              BitsAndBytesConfig, Trainer, TrainingArguments,
                              TrainerCallback)
    from peft import get_peft_model, prepare_model_for_kbit_training
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seq-len", type=int, default=fc.SEQ_LEN)
    ap.add_argument("--epochs", type=int, default=fc.EPOCHS)
    args = ap.parse_args(argv)

    tok = AutoTokenizer.from_pretrained(fc.BASE_MODEL_HF)
    tok.pad_token = tok.pad_token or tok.eos_token
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(fc.BASE_MODEL_HF, quantization_config=bnb, device_map="auto")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, build_lora_config())

    ds = load_dataset("json", data_files=str(fc.TRAIN_JSONL), split="train")
    if args.dry_run:
        ds = ds.select(range(min(16, len(ds))))
    # load_from_cache_file=False: always re-map with the CURRENT code, so a stale
    # cache from an earlier (buggy) format_for_trainer can never be reused.
    # Long examples are tail-truncated to seq_len (keeps the answer) rather than dropped.
    ds = ds.map(lambda e: format_for_trainer(e, tok, args.seq_len),
                remove_columns=ds.column_names, load_from_cache_file=False)
    print(f"prepared {len(ds)} examples (tail-truncated to seq_len={args.seq_len} where needed)")

    targs = TrainingArguments(
        output_dir=str(fc.ADAPTER_DIR), per_device_train_batch_size=fc.MICRO_BATCH,
        gradient_accumulation_steps=fc.GRAD_ACCUM, num_train_epochs=(1 if args.dry_run else args.epochs),
        max_steps=(2 if args.dry_run else -1), learning_rate=fc.LR, lr_scheduler_type="cosine",
        warmup_ratio=0.03, bf16=True, gradient_checkpointing=True, logging_steps=5,
        save_strategy="epoch", report_to=[])

    # Live progress so a long run visibly advances (step/total, %, loss, elapsed, ETA).
    class _Progress(TrainerCallback):
        def on_train_begin(self, a, state, control, **kw):
            self._t0 = time.time()
            print(f"[train] start: {state.max_steps} optimizer steps "
                  f"(epochs={a.num_train_epochs}, grad-accum={a.gradient_accumulation_steps})", flush=True)
        def on_step_end(self, a, state, control, **kw):
            step, total = state.global_step, max(1, state.max_steps)
            if step != 1 and step % 5 != 0 and step != total:
                return
            el = time.time() - self._t0
            frac = step / total
            eta = (el / frac - el) if frac > 0 else 0.0
            loss = next((h["loss"] for h in reversed(state.log_history) if "loss" in h), None)
            print(f"[train] step {step}/{total} ({frac*100:4.0f}%)  "
                  f"loss={loss if loss is not None else '--'}  "
                  f"elapsed={el/60:5.1f}m  eta={eta/60:5.1f}m", flush=True)
        def on_train_end(self, a, state, control, **kw):
            print(f"[train] done: {state.global_step} steps in "
                  f"{(time.time()-self._t0)/60:.1f}m", flush=True)

    # Explicit right-padding collator for our pre-tokenized (input_ids,
    # attention_mask, labels) rows -- avoids DataCollatorForSeq2Seq / tokenizer.pad
    # choking on dict features. Labels pad with -100 so padding is ignored by the loss.
    pad_id = tok.pad_token_id
    def _collate(features):
        maxlen = max(len(f["input_ids"]) for f in features)
        input_ids, attn, labels = [], [], []
        for f in features:
            k = maxlen - len(f["input_ids"])
            input_ids.append(f["input_ids"] + [pad_id] * k)
            attn.append(f["attention_mask"] + [0] * k)
            labels.append(f["labels"] + [-100] * k)
        return {"input_ids": torch.tensor(input_ids),
                "attention_mask": torch.tensor(attn),
                "labels": torch.tensor(labels)}
    Trainer(model=model, args=targs, train_dataset=ds, data_collator=_collate,
            callbacks=[_Progress()]).train()
    model.save_pretrained(str(fc.ADAPTER_DIR)); tok.save_pretrained(str(fc.ADAPTER_DIR))
    print(f"adapter saved -> {fc.ADAPTER_DIR}")

if __name__ == "__main__":
    main()
