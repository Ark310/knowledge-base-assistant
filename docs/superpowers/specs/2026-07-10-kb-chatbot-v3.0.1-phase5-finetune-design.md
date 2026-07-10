# KB Chatbot v3.0.1 — Phase 5: On-Prem Model Fine-Tuning ("Contoso Guru") — Design

**Date:** 2026-07-10
**Status:** Approved (brainstorming) — pending spec review → writing-plans
**Branch:** `feat/kb-chatbot-v3.0.1`

## Goal

Fine-tune the on-prem **Qwen2.5-7B-Instruct** model so it synthesizes Contoso's own
retrieved context into the same high-quality, cited, house-style answers Claude/Codex
produce — **without changing the RAG contract** ("answer only from the retrieved
context; abstain when it isn't supported"). The result is served through the existing
Ollama + Caddy reasoning gateway as `contoso-reasoning-qwen25-7b`, giving the free,
on-prem provider markedly better answers on Contoso products while keeping grounding
and low hallucination risk.

This is **RAG-aware domain/style tuning**, explicitly **not** knowledge injection: we do
not bake facts into the weights (the RAG index already holds the knowledge and stays the
source of truth). Fine-tuning teaches *how to use* retrieved Contoso context, not *what*
the facts are.

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Objective | RAG-aware domain tuning (imitate Claude's synthesis over our context); no knowledge injection |
| Training targets | **Hybrid**: real ticket problem→resolution pairs (coverage/grounding) + a Claude/Codex-distilled slice (house style) + abstain/safety examples |
| Toolchain | `transformers` + `peft` + `bitsandbytes` QLoRA (4-bit), **native Windows** (no WSL) |
| Method | QLoRA adapter on the frozen 4-bit base; merge → GGUF → Q4_K_M for Ollama |
| GPU | **Dedicated window** on the AI PC (KYC paused, Ollama stopped) — training is one-off + occasional refresh |
| Ship gate | Automated eval (quality up **and** abstain-safety not down) + human spot-check; base model = instant rollback |
| Data locality | On-prem. Distilled slice sends only **PII-redacted** context to Claude/Codex — identical to what the live chatbot already sends |

## Constraints

- **Hardware:** AI PC — RTX 5060 Ti **8 GB VRAM**, Windows Server 2019, shared with the KYC
  app (which we must not touch). 8 GB is tight for 7B QLoRA; config must fit within it.
- **Security (org rule, non-negotiable):** *Never include API secret keys, passwords, or
  customer PII* — in the training data or anywhere. Redaction of the training set is a
  **hard, tested gate** before any training runs.
- **Serving parity:** training examples must match the serving prompt exactly (same SYSTEM
  text as `ai_pc/reasoning_gateway/Modelfile.reasoning`, same context layout as
  `Dev/kb_chatbot/prompt.py`), or the tuned model degrades at inference.
- **RAG contract preserved:** the tuned model must still abstain when context is missing.
- **Base model:** `qwen2.5:7b-instruct` (the current gateway base). Tuned tag is versioned
  (`contoso-reasoning-qwen25-7b:v1`); the base tag remains for rollback.

## Architecture / data flow

An offline batch pipeline in five stages. Stages 1 (dataset) + 5 (eval) can run on the dev
machine; stages 2–4 (train/export) run on the AI PC in the dedicated window.

```
                 ┌─────────────── dev machine ───────────────┐        ┌──────── AI PC (window) ────────┐
 tickets + KB ─▶ 1. build_dataset ─▶ redaction GATE ─▶ train.jsonl ─▶ 2. train_qlora ─▶ adapter ─▶ 3. merge
                    (+ distill via                    (probe test,        (QLoRA 4-bit)                    │
                     Claude/Codex)                     hard fail)                                          ▼
                                                                                          4. GGUF + Q4_K_M ─▶ ollama create
 held-out Q&A ─▶ 5. eval_compare (tuned vs base vs Claude + abstain-safety) ─▶ GATE ─▶ flip Modelfile / rollback
```

### Stage 1 — Build the training set (`build_dataset.py`, `distill.py`)

Each example is a chat-format record in the **exact serving shape**:
`{system: <Modelfile SYSTEM>, context: <retrieved chunks, prompt.py layout>, question} → {answer}`.

Three ingredients:

1. **Ticket pairs (bulk, free grounding).** For each *resolved* ticket with a substantive
   resolution: question = ticket problem (title + problem text); context = the chunks the
   **real retriever** returns for that question (run `retriever.retrieve` over the current
   index); target = the ticket's resolution, formatted in the house cited style. Filter out
   unresolved / empty-resolution / trivial tickets.
2. **Distilled style slice (quality, bounded cloud cost).** A curated question set
   (sampled tickets across products + KB how-to questions), a few hundred to ~1–2k items,
   each run through the **real chatbot pipeline** with Claude/Codex; capture (retrieved
   context, model's cited answer); target = that answer. Resumable + cost-logged.
3. **Abstain/safety examples.** Questions whose retrieved context does **not** support an
   answer (low retrieval confidence, or synthetic out-of-scope questions) → target = the
   proper refusal ("that isn't in the KB / here's what's missing"). Present in meaningful
   proportion so tuning reinforces — not erodes — the abstain behavior.

**Redaction gate (hard):** every generated example passes through the same PII/secret
redaction the RAG chunks already get (`ticket_ingest` redaction), then a **probe test**
scans the final JSONL for real emails, phone numbers, secret-key patterns, passwords. Any
hit **fails the build** — training cannot proceed. This test is part of the suite.

Output: `train.jsonl` (+ a held-out `eval.jsonl` split) under an off-repo datasets dir
(gitignored).

### Stage 2 — Train (`train_qlora.py`, `finetune_config.py`)

QLoRA on the frozen 4-bit base:
- 4-bit NF4 quant (bitsandbytes), `bnb_4bit_compute_dtype=bfloat16`.
- LoRA r=16, alpha=32, dropout=0.05, on attention + MLP projections.
- Gradient checkpointing ON; batch size 1 + gradient accumulation (effective ~8–16).
- Seq len 2048, falling back to 1024 if VRAM is tight; 1–2 epochs; cosine LR ~2e-4, warmup.
- Qwen chat template applied; loss on the assistant turn only (mask the prompt).
- Saves the LoRA adapter + a training log; all knobs live in `finetune_config.py`.

A **tiny dry-run** (a few dozen examples, 1–2 steps) validates the end-to-end path + VRAM
headroom before the full run.

### Stage 3–4 — Merge, export, serve (`merge_and_export.py`)

Merge the adapter into fp16 → convert to GGUF (llama.cpp `convert_hf_to_gguf`) → quantize
**Q4_K_M** → `ollama create contoso-reasoning-qwen25-7b:v1 -f Modelfile.reasoning.tuned`
(FROM the tuned GGUF; same SYSTEM + params as the base Modelfile). The gateway keeps both
tags; a script flips the served tag.

### Stage 5 — Eval gate + rollback (`eval_compare.py`)

Expand `Dev/kb_chatbot/eval/` into a held-out Q&A set. Run **tuned-7B vs base-7B vs Claude**
through the orchestrator and score with the existing harness (accuracy + run-to-run
consistency) plus an **abstain-safety** check (feed questions with no supporting context;
the model must refuse). Ship criteria: **tuned ≥ base on quality/consistency AND tuned ≥
base on abstain-safety.** If it passes → operator spot-checks ~10–15 tuned-vs-base answers
→ flip the Modelfile. If it fails → stay on base. Rollback = point the gateway Modelfile
back to the base tag (`08_rollback.ps1`).

## File structure

New package `Dev/kb_chatbot/finetune/`:
- `finetune_config.py` — all paths + hyperparameters (dataset sizes, LoRA/QLoRA knobs, model ids).
- `build_dataset.py` — assemble `train.jsonl`/`eval.jsonl` from tickets + KB via the real
  retriever + `prompt.py` formatting; apply redaction; emit ticket-pair + abstain examples.
- `distill.py` — run Claude/Codex over the curated question set; capture (context, answer)
  targets; resumable, cost-logged.
- `train_qlora.py` — the QLoRA trainer (transformers/peft/bitsandbytes), config-driven, with a `--dry-run`.
- `merge_and_export.py` — merge adapter → fp16 → GGUF → Q4_K_M (invokes llama.cpp).
- `eval_compare.py` — tuned-vs-base-vs-Claude eval + abstain-safety + report.
- `README.md` — operator runbook (window steps: validate env → pause KYC → stop Ollama →
  train → merge/export → eval → flip or rollback).

Gateway bundle additions (`ai_pc/reasoning_gateway/`):
- `Modelfile.reasoning.tuned` (FROM the tuned GGUF), `07_activate_tuned.ps1`, `08_rollback.ps1`.

Off-repo (gitignored): datasets, adapters, GGUFs (large).

## Testing

- **Unit (in the pytest suite):** dataset example formatting matches the serving prompt;
  assistant-only loss masking; abstain-example generation; **redaction/PII-probe test on
  generated examples (hard gate)**; eval scoring + abstain-safety scoring.
- **Operator-run (GPU, not unit-tested):** dry-run train, full train, GGUF export. Their
  gate is `eval_compare`'s numeric report + the spot-check.

## Risks & mitigations

- **8 GB OOM** → 4-bit + grad-checkpointing + batch 1 + seq 1024 fallback; dry-run validates headroom first.
- **PII/secret leakage into weights** → mandatory redaction + probe test as a hard build gate (org rule).
- **Catastrophic forgetting / over-fit** → LoRA (not full FT), 1–2 epochs, abstain examples in the mix, base kept as rollback.
- **Native-Windows bitsandbytes / llama.cpp friction** → pin versions; an env-validation step (mirroring the gateway's `00_validate_env`); document in the README.
- **Distillation cost/time** → cap the distilled slice size; resumable + cost-logged.
- **Regressed abstain behavior** → the abstain-safety check is a ship-blocking gate, not advisory.

## Out of scope

- Knowledge injection / retrieval-off answering.
- Full-parameter fine-tuning; multi-GPU/distributed training.
- Changing the retriever, chunking, or the chatbot app (Phases 1–2/6 own those).
- Auto-retraining pipelines/schedulers (this is a manual, operator-run batch job).

## Phasing (one spec → staged plan)

- **P5.1** dataset build (`build_dataset` + `distill`) + **redaction gate** + unit tests.
- **P5.2** `train_qlora` + `finetune_config` + tiny dry-run (validates path + VRAM).
- **P5.3** full training run in the dedicated window (operator).
- **P5.4** `merge_and_export` → GGUF/Q4_K_M → `ollama create` + gateway activate/rollback scripts.
- **P5.5** `eval_compare` gate + spot-check + flip the served Modelfile (or rollback).
