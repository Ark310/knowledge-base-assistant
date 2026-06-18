# KB Chatbot v2.9.1 — Phase 3: Codex Token Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop GPT-5.4 (over the account-based Codex CLI) from running every answer at `high` reasoning effort — pin it to `low` — cutting reasoning-output tokens ~89% with equal-or-better accuracy, and re-enable the cheaper `gpt-5.4-mini` (which the same change fixes, closing bug-062).

**Architecture:** One-line-ish change in `Dev/kb_chatbot/llm/codex_provider.py` (`_run_codex_exec` adds `-c model_reasoning_effort="low"`), which BOTH the chat and the query-rewrite paths share. Plus a config change to re-offer `gpt-5.4-mini`, and a cost-footnote wording update. No retrieval/orchestrator/UI logic changes.

**Tech Stack:** Python 3, pytest. Tests run with `scraper/venv/Scripts/python.exe -m pytest` from the repo root.

## Spike evidence (codex-cli 0.139, real GPT-5.4, account-based — see `_v291_codex_spike*.py`)

| Config | input | reasoning_out | result |
|---|---|---|---|
| baseline (inherits config.toml `high`) | 17,261 | 262 | 76s; wrongly abstained |
| `-c model_reasoning_effort="low"` | 17,271 | 28 | 33s; correct & complete |
| `model_reasoning_effort="minimal"` | — | — | FAILS: "tools cannot be used with reasoning effort minimal" |
| `low` + `tools.web_search=false` / `--disable web_search` / `--ignore-user-config` | ~17,271 | — | input **unchanged** (no effect) |
| `low` + gpt-5.4-**mini** | 16,919 | 75 | works, correct |

## Global Constraints

- **Account-based only.** No API key. Levers limited to `codex exec` flags.
- **Accuracy wins.** `low` is the floor (minimal is rejected by codex). Validate no accuracy regression before the build.
- **Honest ceiling (document, don't hide):** the ~17k input scaffold is fixed by the Codex CLI and is NOT reducible via flags (measured). This phase cuts reasoning/output waste only; input parity with Claude (~8k) is not achievable account-based.
- **Determinism:** pin reasoning effort explicitly via `-c` so behavior does NOT depend on the user's personal `~/.codex/config.toml` (which currently sets `model_reasoning_effort = "high"`).
- **Test runner:** `scraper/venv/Scripts/python.exe -m pytest <path> -v` from repo root. Imports use `from Dev.kb_chatbot...`.
- **Commit after each task.** Branch: `feat/kb-chatbot-v2.9.1` (Phase 2 ends at `126868d`).
- No reindex/build here (Phase 4).

---

### Task 1: Pin Codex reasoning effort to `low` (token win + bug-062 fix)

**Files:**
- Modify: `Dev/kb_chatbot/llm/codex_provider.py` (`_run_codex_exec` arg list; add a module constant)
- Test: `Dev/kb_chatbot/tests/test_codex_provider.py`; `Dev/kb_chatbot/tests/test_query_rewriter.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `codex_provider.CODEX_REASONING_EFFORT = "low"`; every `codex exec` argv built by `_run_codex_exec` includes `-c model_reasoning_effort="low"`. Both `CodexProvider.chat` and the rewrite path (`query_rewriter._run_codex_exec_for_rewrite` → `_run_codex_exec`) inherit it.

- [ ] **Step 1: Write the failing tests**

Append to `Dev/kb_chatbot/tests/test_codex_provider.py`:

```python
def test_run_codex_exec_pins_reasoning_effort_low(monkeypatch):
    """Every codex exec call must pin model_reasoning_effort=low so it does not
    inherit the user's ~/.codex/config.toml (which may be 'high')."""
    captured = {}

    class _Proc:
        stdout = json.dumps({"type": "turn.completed",
                             "usage": {"input_tokens": 10, "output_tokens": 5}})
        stderr = ""
        returncode = 0

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        out_path = cmd[cmd.index("-o") + 1]
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("ok")
        return _Proc()

    monkeypatch.setattr(cp.shutil, "which", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(cp.subprocess, "run", fake_run)
    cp._run_codex_exec("prompt", "gpt-5.4")
    cmd = captured["cmd"]
    # the -c override is present, with the value the constant defines
    assert "-c" in cmd
    joined = " ".join(cmd)
    assert f'model_reasoning_effort="{cp.CODEX_REASONING_EFFORT}"' in joined
    assert cp.CODEX_REASONING_EFFORT == "low"
```

Append to `Dev/kb_chatbot/tests/test_query_rewriter.py`:

```python
def test_codex_rewrite_inherits_reasoning_low(monkeypatch):
    """bug-062: the OpenAI rewrite path goes through _run_codex_exec, so it now
    pins reasoning=low (which makes gpt-5.4-mini work) and returns a query."""
    from Dev.kb_chatbot.chat import query_rewriter as qr
    captured = {}

    def fake_exec(prompt, model):
        captured["model"] = model
        return ("booking spot deal api", 100, 8)

    monkeypatch.setattr(qr, "_run_codex_exec_for_rewrite", fake_exec)
    res = qr.rewrite_query_codex("how do i do it", [{"role": "user", "content": "spot deal"}])
    assert res is not None
    assert res.query == "booking spot deal api"
    assert captured["model"] == qr.REWRITE_MODEL_OPENAI
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_codex_provider.py::test_run_codex_exec_pins_reasoning_effort_low Dev/kb_chatbot/tests/test_query_rewriter.py::test_codex_rewrite_inherits_reasoning_low -v`
Expected: the codex test FAILS (`AttributeError: module ... has no attribute 'CODEX_REASONING_EFFORT'` / flag absent). The rewrite test may already pass (it stubs `_run_codex_exec_for_rewrite`) — that is fine; it is a regression guard for the bug-062 contract.

- [ ] **Step 3: Implement the pin**

In `Dev/kb_chatbot/llm/codex_provider.py`, add a module constant near the top (after `CODEX_TIMEOUT_S`):

```python
# Pin reasoning effort low for every call. The app is a RAG reformat task, not an
# agentic coding task: 'low' cuts reasoning-output tokens ~89% vs the user's global
# 'high' default with equal/better accuracy (spike: 262 -> ~28 reasoning tok). NOTE:
# 'minimal' is rejected by codex 0.139 ("tools cannot be used with reasoning effort
# minimal"), so 'low' is the floor. Setting it here makes behavior independent of the
# user's ~/.codex/config.toml.
CODEX_REASONING_EFFORT = "low"
```

In `_run_codex_exec`, add the override to the `args` list (after `--ephemeral`/`-C` group, before `-o`):

```python
    args = ["exec", "-m", model, "--json",
            "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
            "-C", tempfile.gettempdir(),
            "-c", f'model_reasoning_effort="{CODEX_REASONING_EFFORT}"',
            "-o", out_path]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_codex_provider.py Dev/kb_chatbot/tests/test_query_rewriter.py -v`
Expected: PASS (new tests + all pre-existing codex/rewriter tests — the existing `test_chat_stubbed_subprocess` / `test_run_codex_exec_*` still pass because they only assert on the `-o` slot and stdout parsing, which are unchanged).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/llm/codex_provider.py Dev/kb_chatbot/tests/test_codex_provider.py Dev/kb_chatbot/tests/test_query_rewriter.py
git commit -m "feat(v2.9.1): pin Codex reasoning_effort=low (cuts reasoning tokens ~89%; fixes bug-062 mini rewrite)"
```

---

### Task 2: Re-enable gpt-5.4-mini + update cost footnote

**Files:**
- Modify: `Dev/kb_chatbot/config.py` (`PROVIDERS["openai"]["models"]` + the explanatory comment)
- Modify: `Dev/kb_chatbot/gui.py` (`TokenUsageDialog` footnote text)
- Test: `Dev/kb_chatbot/tests/test_config_providers.py`

**Interfaces:**
- Produces: `gpt-5.4-mini` selectable in the ChatGPT provider's model list; `gpt-5.4` stays the default.

- [ ] **Step 1: Write the failing test**

Append to `Dev/kb_chatbot/tests/test_config_providers.py`:

```python
def test_openai_offers_gpt54_mini():
    from Dev.kb_chatbot import config
    models = config.PROVIDERS["openai"]["models"]
    assert "gpt-5.4-mini" in models.values()
    # gpt-5.4 stays the default
    assert config.PROVIDERS["openai"]["default_model"] == "gpt-5.4"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_config_providers.py::test_openai_offers_gpt54_mini -v`
Expected: FAIL (mini not in the models map).

- [ ] **Step 3: Re-enable mini + refresh the comment**

In `Dev/kb_chatbot/config.py`, update the `openai` provider entry. Replace the existing comment block + `models` dict with:

```python
    "openai": {
        "display": "ChatGPT",
        # v2.9.1: with model_reasoning_effort pinned to "low" (codex_provider), the
        # Codex CLI no longer rejects gpt-5.4-mini (the earlier 400 was the high/
        # default-effort + injected-tool combo). gpt-5.4 stays default for accuracy;
        # mini is offered as a faster/cheaper option.
        "default_model": "gpt-5.4",
        "models": {
            "GPT-5.4": "gpt-5.4",
            "GPT-5.4-mini (fast / cheap)": "gpt-5.4-mini",
        },
    },
```

In `Dev/kb_chatbot/gui.py`, update the `TokenUsageDialog` footer text. Replace the sentence "ChatGPT counts include Codex's agent overhead, so they read higher than Claude." with:

```python
        "ChatGPT (Codex) runs at low reasoning effort to minimize output tokens, but "
        "its requests carry a fixed Codex agent scaffold (~17k input tokens/turn) that "
        "the account-based CLI always sends, so ChatGPT input reads higher than Claude. "
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests/test_config_providers.py -v`
Expected: PASS (new test + pre-existing provider tests — `test_default_provider_is_claude`, `test_backward_compat_aliases` unaffected; adding a model doesn't change the default or aliases).

- [ ] **Step 5: Commit**

```bash
git add Dev/kb_chatbot/config.py Dev/kb_chatbot/gui.py Dev/kb_chatbot/tests/test_config_providers.py
git commit -m "feat(v2.9.1): re-offer gpt-5.4-mini (works at low effort); update token-cost footnote"
```

---

### Task 3: Full regression + accuracy gate

**Files:**
- Test: full `Dev/kb_chatbot/tests` suite; live golden check (verification, not committed code)

**Interfaces:** consumes Tasks 1-2.

- [ ] **Step 1: Run the full kb_chatbot suite**

Run: `scraper/venv/Scripts/python.exe -m pytest Dev/kb_chatbot/tests -v`
Expected: PASS — all pre-existing + Phase 1/2/3 tests. Fix any regression before proceeding.

- [ ] **Step 2: Live accuracy gate (real Codex, gpt-5.4 at low) — manual verification**

This step is run by the controller (needs the logged-in Codex CLI), not committed. Re-run the spike-style probe on a handful of REAL answerable KB/ticket questions at `low` and confirm: (a) answers are complete and correct (no spurious abstains on answerable questions), (b) format follows the expert structure, (c) `gpt-5.4-mini` also returns a sensible answer. Compare token usage to the `high` baseline to confirm the reasoning-token drop. Record the before/after in the ledger. Accuracy-wins: if `low` shows real accuracy loss vs `high` on this set, STOP and escalate (the spike showed the opposite, so this is a confirmation gate).

- [ ] **Step 3: Update bug-062 in the bug log**

Mark bug-062 (`.wolf/buglog.json`) FIXED: the OpenAI rewrite path now works because `_run_codex_exec` pins `reasoning_effort=low`, under which `gpt-5.4-mini` is accepted by codex 0.139 (verified in the spike + Task 1 test).

- [ ] **Step 4: Commit (if any doc/bug-log changes are tracked)**

```bash
git add -A && git commit -m "test(v2.9.1): Phase 3 regression + accuracy gate; bug-062 fixed"
```
(If only `.wolf/` bookkeeping changed and the repo convention leaves it uncommitted, skip the commit and just record the gate result in the ledger.)

---

## Self-Review

**Spec coverage (Phase 3 = spec §6.1):**
- Reasoning-effort lever → Task 1 (`low`, since `minimal` is rejected — documented). ✓
- Disable injected `_search`/web tool → **dropped with evidence:** the spike measured NO input reduction from `tools.web_search=false` / `--disable web_search` / `--ignore-user-config`, so it is not implemented (would add complexity for zero benefit). The honest input-scaffold ceiling is documented in the footnote (Task 2) and Global Constraints. ✓ (no silent omission)
- Rewrite-model fix (bug-062) → Task 1 (shared `_run_codex_exec` + regression test) + Task 3 Step 3. ✓
- Re-enable cheaper models if confirmed → Task 2 re-adds `gpt-5.4-mini` (confirmed at `low`); `gpt-5.5` NOT re-added (untested). ✓
- Optional shared-context trim (TOP_K) → **dropped:** Codex input is dominated by the irreducible ~17k scaffold, not our ~1k context, so trimming context barely helps Codex and risks accuracy (accuracy-wins). Not implemented. ✓
- Honest ceiling documented → Global Constraints + footnote. ✓

**Placeholder scan:** none — exact flag string, exact config block, exact footnote text, real tests. The accuracy gate (Task 3 Step 2) is intentionally a controller-run manual verification (LLM-nondeterministic), clearly scoped.

**Type consistency:** `CODEX_REASONING_EFFORT` defined in Task 1 and referenced in its test; `_run_codex_exec` arg list is the same one all callers use; `gpt-5.4-mini` string matches `MODEL_DISPLAY`/`COST_TABLE` entries already present in `config.py`.

**Risks:** (1) `low` could in principle abstain more than `high` on some queries — mitigated by the accuracy gate (spike showed `high` abstained, not `low`). (2) Pinning via `-c` overrides the user's config — intended (determinism). (3) `gpt-5.4-mini` quality is lower than `gpt-5.4` — mitigated by keeping `gpt-5.4` the default; mini is opt-in.
