"""Single source of truth for fine-tuning paths + hyperparameters (8 GB-safe)."""
from __future__ import annotations
from pathlib import Path
from Dev.kb_chatbot import config

DATA_DIR      = config.STATE_DIR / "finetune"     # off OneDrive, gitignored
TRAIN_JSONL   = DATA_DIR / "train.jsonl"
EVAL_JSONL    = DATA_DIR / "eval.jsonl"
DISTILL_JSONL = DATA_DIR / "distill.jsonl"
ADAPTER_DIR   = DATA_DIR / "adapter"
MERGED_DIR    = DATA_DIR / "merged_fp16"
GGUF_PATH     = DATA_DIR / "contoso-reasoning-qwen25-7b-Q4_K_M.gguf"

BASE_MODEL_HF = "Qwen/Qwen2.5-3B-Instruct"   # 3B fits 8 GB comfortably (7B thrashed/froze)
BASE_OLLAMA   = "qwen2.5:7b-instruct"
TUNED_TAG     = "contoso-reasoning-qwen25-7b:v1"

# Dataset sizes
MAX_TICKET_EXAMPLES = 4000
DISTILL_QUESTIONS   = 800
ABSTAIN_EXAMPLES    = 400
EVAL_HOLDOUT        = 150

# QLoRA / training (fits 8 GB: 4-bit + grad-checkpointing + micro-batch 1)
SEQ_LEN     = 2048   # drop to 1024 if OOM
EPOCHS      = 2
MICRO_BATCH = 1
GRAD_ACCUM  = 8    # 8 micro-batches/optimizer-step (snappier progress on 8 GB)
LR          = 2e-4
LORA_R      = 16
LORA_ALPHA  = 32
LORA_DROPOUT = 0.05
