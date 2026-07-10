"""QLoRA fine-tune Qwen2.5-7B-Instruct on the redaction-gated train.jsonl.
Native Windows: transformers + peft + bitsandbytes (4-bit NF4). Runs on the AI PC
in the dedicated GPU window. `--dry-run` trains 2 steps on <=16 examples to
validate the path + VRAM before the full run."""
from __future__ import annotations
import argparse
from Dev.kb_chatbot.finetune import finetune_config as fc

def build_lora_config():
    from peft import LoraConfig
    return LoraConfig(
        r=fc.LORA_R, lora_alpha=fc.LORA_ALPHA, lora_dropout=fc.LORA_DROPOUT,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    )

def format_for_trainer(example: dict, tokenizer) -> dict:
    """Qwen chat template; supervise ONLY the assistant turn (mask the rest to -100)."""
    msgs = example["messages"]
    full = tokenizer.apply_chat_template(msgs, tokenize=True, add_generation_prompt=False)
    prompt_only = tokenizer.apply_chat_template(msgs[:-1], tokenize=True, add_generation_prompt=True)
    labels = list(full)
    for i in range(min(len(prompt_only), len(labels))):
        labels[i] = -100
    return {"input_ids": full, "attention_mask": [1]*len(full), "labels": labels}

def main(argv=None) -> None:
    import torch
    from datasets import load_dataset
    from transformers import (AutoTokenizer, AutoModelForCausalLM,
                              BitsAndBytesConfig, Trainer, TrainingArguments,
                              DataCollatorForSeq2Seq)
    from peft import get_peft_model, prepare_model_for_kbit_training
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seq-len", type=int, default=fc.SEQ_LEN)
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
    ds = ds.map(lambda e: format_for_trainer(e, tok), remove_columns=ds.column_names)
    _before = len(ds)
    ds = ds.filter(lambda e: len(e["input_ids"]) <= args.seq_len)
    print(f"kept {len(ds)}/{_before} examples within seq_len={args.seq_len}")

    targs = TrainingArguments(
        output_dir=str(fc.ADAPTER_DIR), per_device_train_batch_size=fc.MICRO_BATCH,
        gradient_accumulation_steps=fc.GRAD_ACCUM, num_train_epochs=(1 if args.dry_run else fc.EPOCHS),
        max_steps=(2 if args.dry_run else -1), learning_rate=fc.LR, lr_scheduler_type="cosine",
        warmup_ratio=0.03, bf16=True, gradient_checkpointing=True, logging_steps=10,
        save_strategy="epoch", report_to=[])
    collator = DataCollatorForSeq2Seq(tok, label_pad_token_id=-100, padding=True)
    Trainer(model=model, args=targs, train_dataset=ds, data_collator=collator).train()
    model.save_pretrained(str(fc.ADAPTER_DIR)); tok.save_pretrained(str(fc.ADAPTER_DIR))
    print(f"adapter saved -> {fc.ADAPTER_DIR}")

if __name__ == "__main__":
    main()
