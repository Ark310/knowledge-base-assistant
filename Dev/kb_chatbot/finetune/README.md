# Operator Runbook: Fine-Tuning Contoso Guru (QLoRA Qwen2.5-7B-Instruct)

## Overview

This runbook guides you through a full on-prem fine-tuning cycle: dataset prep → dry-run validation → training on GPU → export to GGUF → eval gate → swap the served model.

**Why a dedicated window:** The AI PC GPU (RTX 5060 Ti, 8 GB) is shared with the KYC gateway + the currently-served reasoning model. Training requires uninterrupted VRAM; stop the gateway and pause KYC before starting.

**Security (mandatory):** The redaction gate scans all training examples for real email addresses, phone numbers, API keys, and passwords. The build **aborts** if any leak is found. Never proceed past the dataset step if redaction fails.

---

## Step 1: Prepare dataset (dev machine)

### Step 1a: Generate the distilled slice (Claude/Codex house style)
Requires an Anthropic API key. This step captures high-quality reference answers over a curated question set.

```bash
python -m Dev.kb_chatbot.finetune.distill \
  --provider claude \
  --model claude-sonnet-4-6 \
  --questions <path/to/questions.txt> \
  --out <path/to/distill.jsonl>
```

**Expected output:** One JSONL record per question; each is `{"messages": [...]}`. Cost is logged. This is resumable—rerun the same command to skip questions already written.

### Step 1b: Assemble the full dataset (ticket pairs + abstain + distilled)
This merges all sources, runs the hard redaction gate, shuffles deterministically, and splits train/eval.

```bash
python -m Dev.kb_chatbot.finetune.build_dataset \
  --tickets <path/to/library/tickets> \
  --chroma <path/to/chroma_db> \
  --abstain-questions <path/to/out_of_scope.txt>
```

**Expected output:**
```
train=XXXX eval=YYY  (XXXX ticket, NN abstain, ZZ distilled)
```

**If this fails with `LeakError`:** Stop. Do NOT proceed. The dataset contains PII or secrets. Investigate the error message, fix the source, and rerun.

---

## Step 2: Set up the AI PC training environment (one-time)

On the AI PC, in a new Python 3.12+ virtual environment:

```bash
# Create and activate venv (Windows)
python -m venv training_venv
training_venv\Scripts\activate.bat

# Install CUDA-enabled PyTorch
pip install torch --index-url https://download.pytorch.org/whl/cu124

# Install fine-tuning dependencies
pip install transformers peft bitsandbytes datasets accelerate

# Verify CUDA and bitsandbytes
python -c "import torch; print(torch.cuda.is_available())"    # Must be True
python -c "import bitsandbytes"                               # Must not error
```

**Expected:** Both commands print `True` and succeed silently.

---

## Step 3: Open the dedicated GPU window

Before training, free the GPU by stopping competing services.

### Step 3a: Stop the gateway
```powershell
ai_pc\reasoning_gateway\05_stop_gateway.ps1
```

### Step 3b: Pause KYC
Stop the KYC service manually or via your deployment tool. (Confirms no model is resident on GPU.)

### Step 3c: Confirm VRAM is free
```bash
nvidia-smi
```

**Expected:** Shows the GPU with <200 MB in-use (only system). If not, wait or restart the AI PC.

---

## Step 4: Dry-run (validate path + VRAM)

In the training venv on the AI PC:

```bash
python -m Dev.kb_chatbot.finetune.train_qlora --dry-run
```

**Expected:** Trains on ≤16 examples for 2 steps, prints `adapter saved -> ...`, and completes in <5 min without OOM.

**If OOM occurs:** The 8 GB config needs a smaller sequence length:
```bash
python -m Dev.kb_chatbot.finetune.train_qlora --dry-run --seq-len 1024
```
If this also fails, check Step 3c; GPU memory may not be truly free.

---

## Step 5: Full training run

Once dry-run passes, train on the full dataset:

```bash
python -m Dev.kb_chatbot.finetune.train_qlora
```

**Expected:** Runs for ~2–4 hours depending on dataset size and GPU. Prints periodic loss updates and saves the LoRA adapter to the config path. Final message: `adapter saved -> ...`.

**If training crashes:** Check GPU memory (nvidia-smi) and retrain with `--seq-len 1024` if needed.

---

## Step 6: Export to GGUF and serve

Merge the adapter, convert to GGUF, and quantize for Ollama:

```bash
python -m Dev.kb_chatbot.finetune.merge_and_export \
  --llama-cpp <path/to/llama.cpp/checkout>
```

**Expected:** Prints `GGUF -> ...` and the file appears at the config path.

Then activate the tuned model:

```powershell
ai_pc\reasoning_gateway\07_activate_tuned.ps1
```

**Expected:** Creates the Ollama tag `contoso-reasoning-qwen25-7b:v1` and prints `Done. Point the gateway...`.

---

## Step 7: Eval gate (quality + safety check)

Run eval on the held-out set + unsupported questions to confirm the tuned model does not regress. The tuned model must already be served (Step 6) so both `--tuned-model` (default `contoso-reasoning-qwen25-7b`, the served tag) and `--base-model` (default `qwen2.5:7b-instruct`) are reachable through the gateway. Ships with a starter held-out set + unsupported list you can expand:

```bash
python -m Dev.kb_chatbot.finetune.eval_compare --chroma "%LOCALAPPDATA%\ContosoKBChatbot\chroma" --eval-set Dev/kb_chatbot/finetune/eval_holdout.json --unsupported Dev/kb_chatbot/finetune/unsupported_questions.txt
```

**Expected output:** the `BASE` and `TUNED` scores (`accuracy` + `abstain_safety`) and a `GATE: PASS/FAIL` verdict. The gate PASSES only if:
- `tuned accuracy >= base accuracy` AND
- `tuned abstain_safety >= base abstain_safety`

**If PASS:** spot-check ~10-15 tuned-vs-base answers; the tuned model is already the served tag (Step 6 published it), so nothing more to flip.
**If FAIL:** the tuned model lost quality or broke abstain safety — run Step 8 (rollback) to restore the base, then retrain with different data/hyperparameters. The base is always retained for instant rollback.

---

## Step 8: Restore services

### Step 8a: Rollback (if eval gate failed)
```powershell
ai_pc\reasoning_gateway\08_rollback.ps1
```
This re-points the gateway to the base `qwen2.5:7b-instruct` tag.

### Step 8b: Restart the gateway
```powershell
ai_pc\reasoning_gateway\05_start_gateway.ps1
```

### Step 8c: Resume KYC
Start the KYC service and verify it loads the model.

---

## Troubleshooting

| Issue | Check |
|-------|-------|
| **Step 1b fails with `LeakError`** | Read the error message to locate the PII. Remove or redact it in the source data, then rebuild the dataset. |
| **Step 4 OOM (out of memory)** | Confirm KYC + gateway are stopped (Step 3). If still OOM, rerun with `--seq-len 1024`. |
| **Step 5 hangs** | Check nvidia-smi; if GPU is idle, the training is likely waiting for data. Press Ctrl+C and check the TRAIN_JSONL file for corruption. |
| **Step 7 gate fails** | Compare the printed accuracy/safety scores. If the tuned model underperforms, the training may be overfit or the dataset quality is poor. Retrain with reduced `EPOCHS` (in `finetune_config.py`). |

---

## Key Paths

All artifacts live under `config.STATE_DIR / "finetune"` (off OneDrive, gitignored):
- `train.jsonl` — fine-tuning dataset (redaction-gated).
- `eval.jsonl` — held-out evaluation set.
- `adapter/` — LoRA adapter (after Step 5).
- `merged_fp16/` — merged model (after Step 6).
- `contoso-reasoning-qwen25-7b-Q4_K_M.gguf` — quantized GGUF (served after Step 6).
