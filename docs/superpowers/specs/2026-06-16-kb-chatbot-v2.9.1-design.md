# KB Chatbot v2.9.1 — Token Efficiency, Model Parity, Branding, UI Polish & Security Review — Design Spec

**Date:** 2026-06-16
**Status:** Design approved (chat); pending spec review → implementation plan
**Builds on:** v2.8 (internal resourcing, client context, ticket/KB refs, conversation continuity). v3 retrieval overhaul is abandoned and deleted — do not reference it.

---

## 1. Context & Problem

v2.8 works on both providers (Claude + ChatGPT/GPT-5.4-over-Codex), but four things hold it back from an "enterprise-grade, ships-confidently" release:

1. **GPT-5.4 burns far more tokens than Claude.** The chatbot sends both providers the same payload (system prompt ~700 tok + 8 reranked chunks ~5k tok + short history). The gap is in *how* GPT-5.4 is reached: it runs through the **Codex CLI** (`codex exec`), which injects its own large coding-agent scaffold (system prompt + built-in tools incl. `_search`) on every stateless call (~55k input tok/turn, per v2.7 notes), and GPT-5.x emits **reasoning tokens** (billed as output) on top of the answer. GPT-5.4 is accurate but expensive.
2. **No in-app branding.** The exe has a window/taskbar `.ico`, but nothing inside the app shows the Contoso logo — it looks unfinished.
3. **UI reads like a terminal**, not an enterprise tool: default Qt chrome, monospace Consolas chat, ad-hoc inline colors, no cohesive theme.
4. **Out-of-scope handling is blunt.** Unrelated questions get the same generic "not in the knowledge base" reply as borderline-but-related ones, and topic matching can be sharper.

Plus: we want a **security analysis + review** before shipping, and a **latent bug** was found during planning (the Codex query-rewrite path uses a model the current Codex CLI rejects — see §6.1).

## 2. Goals

- **Cut GPT-5.4 token usage substantially** (especially reasoning output and the injected-tool input) **with no measurable accuracy loss** on the 97-case golden set ("accuracy wins"), narrowing the gap toward Claude.
- **Brand the app**: Contoso logo in the header, welcome/empty state, About dialog, and a launch splash.
- **Enterprise-grade UI**: cohesive theme, readable chat, tidy layout — without removing any existing feature.
- **Smarter out-of-scope behavior** (3-tier) + more accurate topic matching.
- **Security analysis + review** with findings; ship a hardened build.
- **One single exe**, same one-folder layout style as v2.8.

## 3. Non-Goals

- **No OpenAI API-key path.** Stay account-based (Codex CLI). True token parity (which needs the direct API) is explicitly deferred. We narrow the gap; we do not claim identical counts.
- **No retrieval-engine rewrite.** Threshold tuning + the existing rerank pipeline only; no BM25/hybrid/reranker swap (that was the abandoned v3 line).
- **No scraper changes.**
- **No change to the redaction guarantees** — security review may *tighten*, never loosen, and any behavior/goal-affecting security change is brought to the user first.
- **No functional removals** in the UI work (Learn Mode, attachments, reindex, token usage, drag-drop, Ctrl+V all preserved).

## 4. Locked Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| OpenAI auth/billing | **Account-based Codex CLI only.** No API key. Reduce tokens within the CLI's limits. |
| Token vs quality trade-off | **Accuracy wins.** Lower reasoning effort / trim only as far as the golden set shows **no measurable accuracy loss.** Savings are capped by quality. |
| Logo placement | **All four:** header bar, welcome/empty state, About dialog, launch splash. |
| UI scope | **Polish + layout tweaks** (cohesive theme + control regrouping), not a full redesign. |
| Out-of-scope | **3-tier:** clearly-unrelated → "outside scope" (no suggestions); related-but-unclear → one clarifying question + suggested topics; clear → answer. Plus improved matching. |
| Logo rendering | **Pre-rasterize the SVG to PNG(s)** and bundle via the spec; load freeze-aware. No runtime SVG dependency. |
| Release shape | **One single exe**, same one-folder style as v2.8. No side build. |
| Build gate | **Smoke test + explicit user confirmation before any exe compile** (standing rule). |
| Security-affecting changes | **Ask the user first** before applying anything that changes behavior/goals. |

## 5. Approach

Six independent workstreams, each verifiable on its own, sequenced so token work (highest uncertainty) is proven before the cosmetic work:

1. **Codex token reduction** — measurement spike → flag tuning (reasoning effort, disable injected tool) → rewrite-model fix → optional shared-context trim, each gated by the golden set.
2. **Out-of-scope 3-tier + matching** — new threshold + messages in the orchestrator/prompt, tuned on the golden set.
3. **Logo/branding** — rasterized assets bundled + loaded freeze-aware; header/welcome/About/splash.
4. **UI polish** — app-wide QSS theme + chat restyle + control regrouping.
5. **Security analysis + review** — full-corpus probe + bundle/keyring/logging/sandbox audit; report; user sign-off on goal-affecting changes.
6. **Version + housekeeping** — bump to 2.9.1, tests, fresh-workpath build, re-ship index.

## 6. Detailed Design

### 6.1 Codex token reduction — `Dev/kb_chatbot/llm/codex_provider.py`, `chat/query_rewriter.py`, `config.py`

**Measurement spike (first, before any change).** Instrument `_run_codex_exec` / `_parse_usage` to record the input / output / reasoning-token breakdown per call, run a fixed golden-question set on GPT-5.4, and capture a **baseline**. Every lever below is then measured against this baseline for both token delta **and** accuracy (must hold).

**Levers (account-based):**

- **Reasoning effort.** Add a Codex config override to `_run_codex_exec`'s argv — candidate `-c model_reasoning_effort="minimal"` (exact key/values confirmed in the spike against codex 0.139 + gpt-5.4). This is a RAG reformat task, so minimal/low reasoning is expected to preserve accuracy while cutting the dominant **output** cost. Per "accuracy wins": choose the **lowest effort that shows no measurable golden-set accuracy loss** (try minimal; step up to low/medium only if accuracy or format adherence drops).
- **Disable the injected `_search`/web tool.** Candidate `-c` override (exact key confirmed in spike). This trims the **input** scaffold **and** is expected to unblock `gpt-5.4-mini` / `gpt-5.5` (they currently 400 on the tool's `anyOf` schema). If confirmed, re-add those models to `config.PROVIDERS["openai"]["models"]`.
- **Optional shared-context trim.** Only if the golden set shows recall holds: reduce `TOP_K_RERANK` (8→6) and/or cap per-chunk chars. Applies to **both** providers. Skipped if it costs any accuracy.

**Rewrite-model fix (bug-062).** `query_rewriter.rewrite_query_codex` uses `REWRITE_MODEL_OPENAI="gpt-5.4-mini"`, which the current Codex CLI rejects → the escalation always fails on the OpenAI provider after wasting a call. Fix, in priority order pending the spike: (a) if disabling `_search` makes `gpt-5.4-mini` work, keep it (cheapest) + minimal reasoning; else (b) switch to `gpt-5.4` with minimal reasoning; else (c) gate the rewrite escalation off for Codex. Whichever lands, the rewrite call also runs at minimal reasoning effort.

**Honest ceiling (documented in the spec + the Token Usage dialog footnote):** these levers attack the two biggest sinks (reasoning output, injected-tool input) and bring Codex much closer to Claude, but the CLI's base coding-agent scaffold cannot be fully removed account-based. The existing footnote in `TokenUsageDialog` is updated to reflect the reduced-but-nonzero overhead.

### 6.2 Out-of-scope 3-tier + topic matching — `chat/orchestrator.py`, `prompt.py`, `config.py`

Today, gating keys off `result.rerank_top_score` against `CONFIDENCE_FLOOR` (0.06) and `LOW_CONFIDENCE_CEILING` (0.35), and abstain yields `ABSTAIN_WITH_SUGGESTIONS_TEMPLATE` or `ABSTAIN_MESSAGE`. Changes:

- Add `OUT_OF_SCOPE_FLOOR` (new, very low; value set empirically on the golden set) in `config.py`.
- **Tier logic in the abstain branch of `handle_turn`:**
  - `rerank_top_score < OUT_OF_SCOPE_FLOOR` → **out-of-scope**: a concise, polite message — *"That's outside the scope of the Contoso knowledge base, which covers API, TradeDesk, SalesHub, Web2, Web4 and related docs."* No suggestions, no rephrase escalation.
  - `OUT_OF_SCOPE_FLOOR ≤ score < CONFIDENCE_FLOOR` (related but weak) → keep the **clarify + suggested topics** path; this is where the query-rewrite escalation stays active.
  - `≥ CONFIDENCE_FLOOR` → answer (unchanged), with the existing low-confidence footer below `LOW_CONFIDENCE_CEILING`.
- New constant message `OUT_OF_SCOPE_MESSAGE` in `orchestrator.py`; the existing short-query/clarify/abstain messages stay.
- **Better matching:** tune `OUT_OF_SCOPE_FLOOR` / `CONFIDENCE_FLOOR` / `LOW_CONFIDENCE_CEILING` on the golden set so genuinely-unrelated queries fall under the out-of-scope floor while related ones land in clarify/answer. No new retrieval components.
- The system prompt's rule 2 wording is aligned so the LLM's own "not enough info" fallback matches the new scope language (no contradiction between the deterministic gate and the model's text).

### 6.3 Logo + branding — assets, `ContosoKBChatbot.spec`, `Dev/kb_chatbot/gui.py`, `config.py`

- **Assets:** rasterize `Contoso_Logo.svg` to PNG(s) at a small set of sizes (e.g. a header height ~28–32px and a larger welcome/splash size), checked into an `assets/` folder. (One-off rasterization; no runtime SVG dependency.)
- **Bundling:** add the PNG(s) (and keep `contoso.ico`) to the spec `datas` so they ship under `_MEIPASS`.
- **Freeze-aware loader** in `gui.py`: a small `_asset_path(name)` helper resolving `sys._MEIPASS`/assets when frozen and the repo `assets/` when not (mirrors the HF_HOME pattern).
- **Header bar:** a top widget above the controls row — logo + "Contoso KB Assistant" + `v{APP_VERSION}`.
- **Welcome/empty state:** before the first message, the chat area shows a centered logo + one-line hint; replaced on first turn.
- **About dialog:** new `AboutDialog` (logo, version, build, active provider/CLI status) opened from a new **Help → About** toolbar action.
- **Splash on launch:** a lightweight `QSplashScreen` (logo) shown in `main()` while the window builds / InitWorker warms up; closed on `ready`.

### 6.4 UI polish + layout — `Dev/kb_chatbot/gui.py`

- **App-wide QSS theme** applied in `main()` (`app.setStyleSheet(...)`): Contoso brand palette, **Segoe UI** base font, consistent control sizing / border-radius / padding, WCAG-aware contrast. Centralize colors so the ad-hoc inline `setStyleSheet` calls (feedback bar, correction panel, attachment chips) read from one palette.
- **Chat restyle (`_append` / `chat_view`):** move off monospace Consolas to the theme font; render **message bubbles** distinguishing user vs AI vs system, with clearer citation link styling. Keep the existing `[Title](url)` → `<a>` conversion and HTML-escaping (no security regression in rendering).
- **Layout tweaks:** group Product / AI Provider / Model into a tidy labeled control bar under the header; style the toolbar; uniform buttons/inputs. Thinking indicator, progress bar, attachment bar, Learn-Mode feedback bar, correction panel all restyled to the theme but functionally unchanged.
- **Preserved behavior:** all signals/handlers, Learn Mode, attachments (drag-drop + Ctrl+V), reindex dialog, token-usage dialog, settings, STOP/cancel, provider preflight.

### 6.5 Security analysis + review — (analysis task; code changes only with user sign-off)

Produce a findings report covering:
- **PII/secret redaction:** re-run the full-corpus probe (must stay **`email_leaks = 0`**); re-verify the v2.8 relaxation (org name dropped from `known_terms`) didn't open a leak; spot-check credential/secret patterns.
- **Shipped index:** confirm the bundled Chroma index contains only **redacted** chunk text and metadata (no raw tickets, no customer-individual PII).
- **Bundle:** confirm no secrets/keys/passwords are packaged into the exe; confirm the SDK's bundled `claude` CLI is still excluded.
- **Keyring / auth:** Learn-Mode password remains hashed (`learn_mode_hash`); no plaintext secrets on disk; Codex/Claude auth stays in the user's CLI (no creds in app state).
- **Logging:** verify `run.log` / `usage.jsonl` never record PII or secrets (usage records store token counts + ids only).
- **Subprocess sandbox:** Codex stays `--sandbox read-only --ephemeral`; Claude SDK usage unchanged.
- **Dependencies:** quick CVE/version sanity check on the pinned deps.

Findings are reported to the user. **Hardening that changes behavior or goals is proposed and approved before implementation.** Per org policy, no API keys / passwords / customer PII are introduced or logged (staying account-based means no new secret).

### 6.6 Version + housekeeping — `config.py`, `ContosoKBChatbot.spec`, tests

- `APP_VERSION = "2.9.1"` (single source of truth; drives window title, splash/About, and exe name via the spec).
- Update `test_version` to assert `2.9.1`.
- Build into a **fresh `--workpath`** (OneDrive `WinError 5` avoidance, per cerebrum); `COLLECT --noconfirm` recreates `dist/<name>`, so **re-copy the prebuilt index** into `chatbot_state/` after the build (same one-folder layout as v2.8).
- Tidy the stale "v3-beta bge rerankers" comment in the spec (the v3 line is gone).

## 7. Testing

- **Codex provider:** unit test that `_run_codex_exec` argv includes the reasoning-effort (and tool-disable) overrides; usage parsing still returns `(input, output+reasoning)`; existing Windows `.CMD`-shim and error-on-stdout tests stay green.
- **Query rewriter:** test that the OpenAI rewrite uses a model the CLI accepts (per the chosen fix) and that failure still returns `None` (best-effort contract preserved).
- **Orchestrator out-of-scope:** new tests — score `< OUT_OF_SCOPE_FLOOR` → out-of-scope message (no suggestions, no rewrite); `OUT_OF_SCOPE_FLOOR ≤ score < CONFIDENCE_FLOOR` → clarify + suggestions; `≥ CONFIDENCE_FLOOR` → answer. Existing clarify/abstain/continuity tests stay green.
- **Golden set:** before/after token report for GPT-5.4 (input / output / reasoning) **and** accuracy (recall@8, MRR, false-abstain) showing **no measurable accuracy loss**; same run confirms format adherence at the chosen reasoning effort.
- **Assets/branding:** `_asset_path` resolves in both frozen and source modes (mockable); About/splash construct without error in an offscreen test where feasible.
- **Version:** `test_version` asserts `2.9.1`.
- **Security:** full-corpus probe asserts external customer email/phone/secret leaks = 0 (org names + internal usernames allowed, as v2.8).

## 8. Verification before build (standing rule)

1. Full test suite green (Claude + Codex provider paths, orchestrator tiers, version).
2. Golden-set token + accuracy report attached; reasoning effort chosen = lowest with no accuracy loss.
3. Source-run scenarios on **both** providers: (a) in-scope how-to answers identically in substance; (b) clearly-unrelated question → "outside scope"; (c) related-but-vague → clarify + suggestions; (d) GPT-5.4 token usage visibly reduced in the Token Usage dialog.
4. Branding visible from source: header logo, welcome state, About, splash.
5. Security report reviewed; any goal-affecting hardening approved.
6. **Smoke test + user confirmation**, then bump version, build into fresh `--workpath`, re-copy the prebuilt index, confirm in the exe.

## 9. Risks

- **Token parity overpromise** — mitigated by stating the account-based ceiling up front (spec + in-app footnote); we narrow, not equalize.
- **Codex flag uncertainty** — exact `-c` keys for reasoning effort / tool-disable are confirmed empirically in the spike before relying on them; if a lever doesn't exist on codex 0.139, it's dropped and the report says so (no silent assumption).
- **Reasoning-effort accuracy hit** — bounded by "accuracy wins": effort is only lowered as far as the golden set tolerates; format-adherence is part of the gate.
- **Threshold tuning over/under-abstaining** — `OUT_OF_SCOPE_FLOOR` set from golden-set data, not guessed; both directions tested.
- **UI restyle regressions** — functional handlers untouched; QSS/theme only; HTML-escaping in chat preserved (no rendering security regression).
- **Re-enabling gpt-5.4-mini/5.5** — only if the spike confirms they pass with `_search` disabled; otherwise they stay out and gpt-5.4 remains the single ChatGPT model.
- **OneDrive build lock** — fresh `--workpath` per cerebrum; re-copy index after `COLLECT`.
