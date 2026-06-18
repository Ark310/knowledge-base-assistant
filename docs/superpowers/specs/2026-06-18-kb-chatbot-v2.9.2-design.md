# KB Chatbot v2.9.2 — Clarification & Context-Bridging, Ticket-Pool + KB Referencing, FormFlow Taxonomy, UI Fixes — Design Spec

**Date:** 2026-06-18
**Status:** Design approved (chat); pending spec review → implementation plan
**Builds on:** v2.9.1 (parent-document ticket reassembly, output PII scrub, 3-tier out-of-scope, Codex reasoning=low, enterprise UI). v2.9.1 is merged to master.

---

## 1. Context & Problem

Real alpha testing by a team member (chat logs in `state/chats/`, 2026-06-16) surfaced friction. Replaying both conversations on the **current v2.9.1 build** (reindexed v3 index, Claude) shows what's already fixed vs. what remains:

- **CONV B (GetWebDeal null buy amount):** now works end-to-end — T1 full Ticket #75919 answer; T2 "who works on these / which client?" → answered (Monex USA; nimra CSQA owner) — the v2.8 **context-loss is already fixed**; T3 "ticket 75919" → answered fully — the v2.8 **ID-pin failure is already fixed**. ✅ (So continuity-carry + ID-pin are NOT v2.9.2 work.)
- **CONV A (drawdown margin duplication):** friction **still reproduces** — T1 (a detailed, specific question) → product clarification; T2 ("TD Client Server" + client history + who handled) → the bot **drops the detailed Turn-1 question and re-clarifies** ("which specific issue? margin duplication, incorrectly booked drawdowns, …?"); the user must repeat "drawdown margin duplication" (T3) before getting the (excellent) answer. ❌

Root cause of CONV A: after a clarification is answered, the LLM treats the short reply as the question, sees several related tickets in CONTEXT, and asks **another** clarifying question (system-prompt rule 4) instead of answering the original detailed ask. The orchestrator fuses the prior question for *retrieval* but the LLM's user message stays the raw reply.

Plus three user-reported items:
1. **Ticket-pool + KB referencing is "hit or miss" — the #1 complaint: it "feels like a search engine on steroids, not a chatbot for all the data."** The engine aggregates well *when it answers* (CONV A T3 cited #54000 Litware + #45615 Monex USA; CONV B cited #75919), but: (i) errors can live on tickets **or** the KB; (ii) the same error is recorded across **multiple tickets with slightly different wording**; and (iii) it tends to cite **old** tickets and **doesn't actively bridge to newer ones** — root cause confirmed: tickets carry `created_at` but it's **entirely unused** (not in the chunk, no recency signal in retrieval). The bot must feel like it *knows the whole pool + KB* and synthesizes across it, not just returns top matches.
2. **Product taxonomy:** **FormFlow** is a standalone product, **separate from SalesHub**; **FormFlow ≡ FormFlow** (FormFlow = the older version embedded in TradeDesk/other apps; FormFlow = the standalone product). Today the app's `config.PRODUCTS` **omits the forms product entirely** (KB tags it `formflow`, tickets tag it "FormFlow", but it's a "ghost" — no dropdown/display/prompt entry), and ticket raw Project values ("SalesHub", "FormFlow") don't match KB slugs.
3. **UI:** the chat **scrolls to the top on every prompt** (forcing a manual scroll to the bottom), the chat screen "seems basic," and the v2.9.1 deferred nits remain.

## 2. Goals

- **Answer-first, clarify-once, never-lose-context**: eliminate the redundant re-clarification + context-loss (fix CONV A) while still asking a clarifying question when genuinely warranted — without sacrificing accuracy (citations/abstain guarantees intact).
- **Be a guru over the ticket pool AND the KB — feel like a chatbot that knows all the data, not search.** Reliably surface relevant tickets *and* KB for an error; **bridge old↔new tickets** (recency-aware, prefer the latest fix, surface dates); **synthesize across the pool** (the error's history: occurrences, clients, dates, most-recent fix, who handled) with light proactive touches — every claim cited, abstain when unsure (breadth never costs accuracy).
- **Correct product taxonomy**: FormFlow as a first-class product, FormFlow recognized as its synonym, SalesHub separate; consistent product handling across tickets and KB.
- **UI**: fix the scroll-to-top bug, apply the deferred nits, light chat-screen polish.

## 3. Non-Goals

- **No continuity-carry or ID-pin changes** — the replay shows v2.9.1 already fixed those (CONV B). Don't touch them beyond not regressing.
- **No retrieval-engine swap** (no BM25/hybrid/reranker-model change). Strengthening reuses the existing embed+rerank pipeline + query-time augmentation.
- **No full product-taxonomy re-architecture** — normalize the forms/SalesHub (and obvious TD/Web) Project values; don't redesign the whole ticket Project namespace.
- **No new LLM provider / account model.**
- **No security regression** — the v2.9.1 redaction/scrub guarantees stay.

## 4. Locked Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Clarification policy | **Answer-first, clarify-once, never lose context.** Clarify only when genuinely multiple distinct answers; after a clarification is answered, FUSE the original question + reply and ANSWER — never re-clarify the same thread. |
| Referencing scope | **Both** — fix the friction AND strengthen retrieval (balanced KB+ticket; cross-ticket similar-error surfacing). |
| Old vs new tickets | **Aggregate all occurrences + prefer the latest fix** (surface dates; lead with the most recent ticket's resolution, note older). Add `created_at` to the ticket chunk (currently unused). |
| "Smart enough" feel | **Mainly cross-pool synthesis** (root cause + resolution + the error's pattern across the pool: occurrences/clients/dates/most-recent/handlers) **with light proactive touches** (related issues, likely next step, "want more?"). |
| Breadth vs accuracy | **Broaden + synthesize, every claim cited, abstain when unsure.** Breadth must not cost accuracy. |
| FormFlow | First-class forms product. **FormFlow / FormFlow / FormFlow = one bucket** for retrieval/filtering; **SalesHub separate.** Label **FormFlow** for the standalone product, **FormFlow** for the TradeDesk/other-app embedded version (LLM decides by context). |
| UI scope | Scroll-to-top fix + deferred v2.9.1 nits + **light** chat-screen polish (no restructure). |
| Continuity/pin | **Out of scope** — already fixed in v2.9.1 (verified by replay). |

## 5. Approach

Four workstreams, sequenced so the engine fixes (highest value, highest uncertainty) precede the cosmetic UI work:

1. **Clarification & context-bridging** (orchestrator + prompt) — the core fix for CONV A.
2. **Ticket-pool + KB retrieval strengthening** (orchestrator/retriever) — balanced sources + cross-ticket aggregation, golden-tuned.
3. **FormFlow taxonomy** (config + prompt + ticket_ingest normalization; reindex) — first-class forms product + synonyms + context labeling.
4. **UI fixes** (gui) — scroll fix + nits + light polish.

## 6. Detailed Design

### 6.1 Clarification & context-bridging — `chat/orchestrator.py`, `prompt.py`

**(a) Fuse the original question into the LLM's message after a clarification.** In `handle_turn`, when `session.last_assistant_kind() == "clarification"`, the user's current message is a *reply* to that clarification. Today `_build_retrieval_query` fuses prior+reply for retrieval only. Add: build the **effective user message** the LLM sees as a fused form that makes the original ask explicit, e.g. append a bridging note (mirrors the existing `DRIFT_NOTE` mechanism):
```
[CLARIFICATION ANSWERED — the user's original question was: "<original question>". They have now specified: "<reply>". Answer that original question directly using CONTEXT. Do NOT ask another clarifying question.]
```
The "original question" is the last user turn *before* the clarification (`session` already stores turns). This keeps the LLM anchored on Turn-1's specifics.

**(b) Suppress the clarify gate after a clarification.** In both clarify-gate sites in `handle_turn` (the answer-branch `_needs_clarification_from_quick` check and the abstain-branch one), add `session.last_assistant_kind() != "clarification"` to the guard, so the orchestrator never asks a second clarification immediately after one.

**(c) System-prompt rule (anti-re-clarify + clarify-once).** Amend rule 4 in `prompt.SYSTEM_PROMPT`:
- "Ask **at most one** clarifying question per topic. If your previous message in this conversation was a clarifying question and the user has now responded, you **MUST** answer using the full conversation — do **not** ask another clarifying question."
- "Only ask when the answer genuinely **differs** between the candidates. If the same answer applies across products/topics, answer it and note where it also applies, rather than asking."

**(d) Accuracy preserved.** Fusing only re-states the user's own prior words; the CONTEXT-only and citation rules (1, 3, 11) are unchanged, and the bot still abstains when the answer isn't in context.

### 6.2 Ticket-pool + KB referencing — broaden, bridge old↔new, synthesize — `chat/orchestrator.py`, `retriever.py`, `prompt.py` *(the core "feels like search, not a chatbot" fix — biggest complaint)*

The #1 complaint: the bot "feels like a search engine on steroids, not a chatbot for all the data" — it cites whatever ranks top (often an **old** ticket) and doesn't actively bridge to **newer** tickets or synthesize across the pool. Fixes:

**(a) Recency awareness (new).** Tickets carry `created_at` (e.g. `2024-08-22 6:37 AM`) but it is completely unused — not in the chunk, not in retrieval. Add the ticket date to the chunk (metadata `created_at`, parsed to an ISO date, + a `Date: <YYYY-MM-DD>` line in the chunk text) so aggregation and the LLM can reason about old vs. new. (Implemented in `ticket_ingest`, §6.3; reindex.)

**(b) Broaden + balance retrieval for error/issue questions.** Add `_looks_like_error(query)` (keywords: error, issue, fail, "not working", null, exception, "doesn't", incorrect, discrepancy, crash, wrong, …). For that path, **widen the candidate pool** (a higher top-K than the how-to default) and **ensure BOTH sources** are represented: keep v2.9.1's `_ensure_kb_alongside` (attach KB when ticket-dominated) and add the symmetric `_ensure_tickets_alongside` (attach tickets when KB-dominated). Pure how-to questions stay tight/KB-focused.

**(c) Cross-ticket, cross-time aggregation — bridge old↔new.** When a ticket is in the answer context, run a bounded secondary retrieval seeded by the error signature (`kind == "ticket"`, dedup by `ticket_id`) and merge the additional distinct tickets covering the same error — **explicitly including the most recent occurrence** so old AND new tickets are bridged (not just the top semantic match). Parent-document expansion (v2.9.1) assembles each surfaced ticket fully.

**(d) Synthesis + recency in the answer (prompt).** The system prompt directs an **expert, pool-aware** answer for errors: root cause + resolution, **leading with / preferring the most recent ticket's fix as authoritative** (older occurrences noted), plus a brief **cross-pool synthesis** — "seen on N tickets across [clients], from [oldest date] to most recent **[Ticket #X](url)** ([date]); handled by [owners]". Add **light proactive touches** — offer the closest related issue(s) and a likely next step, and invite "want the full list / more detail?" — without padding. Every factual claim keeps its `[Ticket #N](url)` / `[KB title](url)` citation, and it still **abstains when the answer isn't in context** — breadth never costs accuracy.

**(e) Tuning, not guessing.** The error-gate, widened top-K, extra-ticket count, recency preference, and the secondary-pull relevance floor are tuned on the golden set so recency-bridging + synthesis raise the "knows-everything" feel without dragging in irrelevant tickets.

### 6.3 FormFlow taxonomy — `config.py`, `prompt.py`, `ticket_ingest.py`, `chat/orchestrator.py`

**(a) First-class forms product.** Add the forms slug to `config.PRODUCTS` and `PRODUCT_DISPLAY` with display **"FormFlow"**. Use the existing KB slug `formflow` as the canonical slug (KB articles already carry it) so no KB re-tag is needed; `PRODUCT_DISPLAY["formflow"] = "FormFlow"`.

**(b) Synonyms + product detection.** A synonym map so "formflow", "formflow", "formflow", "formflow" all resolve to the `formflow` slug in: the product dropdown (offer "FormFlow"), `_mentions_product`/`_extract_single_product` (orchestrator), and the clarifier display. **SalesHub ("SalesHub"/"saleshub") stays a separate product.**

**(c) Ticket Project → slug normalization.** In `ticket_ingest`, normalize the raw ticket "product" (Project) value to the canonical slug for the cases the taxonomy cares about: `"FormFlow" → formflow`, `"SalesHub" → saleshub`, the `TD …` family → `tradedesk`, `TD Web Portal V2.0 → web2`, `… V4.0 → web4`, `Rest API`/`TD Web API` → `api`; anything unmapped → `other` (and keep the raw Project string in a separate metadata field, e.g. `project`, for display/clarification). This makes product filtering/clarification consistent across tickets and KB. **Requires a reindex** (metadata change) → bump `CHUNK_SCHEMA_VERSION`.

**(c-2) Recency date in the ticket chunk (for §6.2).** Parse `created_at` (e.g. `"2024-08-22 6:37 AM"`) to an ISO date; store it in chunk metadata (`created_at`) and prepend a `Date: <YYYY-MM-DD>` line to the chunk header text, so the answer layer can prefer the latest fix and cite dates. Robust parse with a graceful fallback (empty/unparseable → no date line, no crash). Same reindex.

**(d) Prompt + scope copy.** Update `SYSTEM_PROMPT`'s product list and `OUT_OF_SCOPE_MESSAGE` to include **FormFlow**, and add a rule: "FormFlow is the standalone forms product; FormFlow is the older forms version embedded in TradeDesk and other apps — they are the same product. Refer to it as **FormFlow** when the user asks about the standalone product, and **FormFlow** when discussing the TradeDesk/embedded version. SalesHub is a separate product."

### 6.4 UI fixes — `Dev/kb_chatbot/gui.py`

**(a) Scroll-to-top fix.** In `_append`, after `chat_view.append(block)`, move the cursor to the end and pin the scrollbar to the bottom so the latest message is shown:
```python
self.chat_view.moveCursor(QTextCursor.End)
sb = self.chat_view.verticalScrollBar(); sb.setValue(sb.maximum())
```
(Replaces the current `ensureCursorVisible()` which scrolls to the cursor-at-position-0 → top. Welcome-state `setHtml` path unchanged.)

**(b) Deferred v2.9.1 nits.** Remove the dead `bb.accepted.connect(self.accept)` in `AboutDialog` (Close-only box); add `max-width` to the welcome-hint wrapper so it stays centered/bounded.

**(c) Light chat-screen polish.** Spacing/readability tweaks on the chat surface (consistent message padding, comfortable line-height), confirm auto-scroll-to-latest, no layout restructure. All existing features/handlers preserved.

### 6.5 Version + reindex/build — `config.py`, tests, spec/.bat

Bump `APP_VERSION` 2.9.1 → **2.9.2** (title/About/exe name + `test_version`); bump `CHUNK_SCHEMA_VERSION` for the §6.3(c) ticket Project normalization; reindex + rebuild + re-ship the index (fresh `--workpath`), gated by a smoke test + user confirmation before compile.

## 7. Testing

- **Clarification/bridging (deterministic, FakeProvider):** when the previous assistant turn is a clarification, (i) the LLM message includes the fused original question + the anti-re-clarify bridging note; (ii) the orchestrator clarify gate is suppressed; (iii) a follow-up answering a clarification yields `kind="answer"`, not `clarification`.
- **Anti-re-clarify replay regression:** replay CONV A through a FakeProvider that echoes its prompt; assert Turn-2 produces an answer-shaped turn carrying the original "margin duplication" specifics (no second clarification). Replay CONV B asserts continuity-carry + pin still work (no regression).
- **Retrieval strengthening + recency:** error-type query with only KB in top-K → a ticket attached; ticket-dominated → a KB chunk attached (existing); `_looks_like_error` true → widened top-K; a ticket in context → ≥1 additional distinct same-error ticket merged when one exists; pure how-to → no spurious ticket pull. **Recency:** ticket chunk metadata has `created_at` (ISO) and a `Date:` line in text; `created_at` parses from the raw `"YYYY-MM-DD h:mm AM"` format (and unparseable → no date line, no crash); given two same-error tickets with different dates in context, the aggregation/answer-shaping prefers/leads with the newer one.
- **Synthesis (deterministic where possible):** with a FakeProvider echoing context, the built prompt for an error question contains the recency + cross-pool synthesis directive and ≥2 tickets' dates; the answer carries citations on every claim. (Qualitative synthesis quality is checked in the live golden gate.)
- **Taxonomy:** `formflow` in `PRODUCTS`/`PRODUCT_DISPLAY` ("FormFlow"); "formflow"/"formflow"/"formflow" → `formflow` slug; "saleshub" → `saleshub` (separate); `ticket_ingest` maps Project "FormFlow"→formflow, "SalesHub"→saleshub, "TD Client Server"→tradedesk, and keeps the raw `project`.
- **UI:** a render/scroll helper test (cursor-to-end / scrollbar-max invoked on append); AboutDialog has no dead accept wire.
- **Version:** `test_version` asserts `2.9.2`. **Full suite green.**
- **Live golden gate (both providers):** CONV A answers without forcing a repeat; an FormFlow question is recognized; an error question surfaces tickets + KB.

## 8. Verification before build (standing rule)

1. Full suite green.
2. Reindex from source (schema bump); confirm ticket chunks carry normalized `product` slug + raw `project`; extended secret probe still `leaks=0`.
3. Source smoke (both providers): replay CONV A → no double-clarify / no forced repeat; CONV B → still good; an FormFlow vs SalesHub question; an error question → tickets + KB + similar tickets; UI scroll stays at the latest message.
4. **Smoke test + user confirmation**, then bump version, build (fresh `--workpath`), re-copy index, confirm in the exe.

## 9. Risks

- **Over-suppressing clarification** → answering an ambiguous question wrongly. Mitigated: only suppress *re*-clarification after one was already asked+answered; first-time genuine ambiguity still clarifies; accuracy/citation guarantees unchanged; golden-tuned.
- **Cross-ticket pull / broadened top-K adds noise or latency** → irrelevant tickets in context. Mitigated by a relevance floor + small bounded count + dedup; pure how-to gated out; every claim cited so noise is visible/checkable; golden-tuned.
- **Recency preference surfaces a recent-but-less-relevant ticket** → leading with the newest could demote the truly-relevant older one. Mitigated: prefer-latest applies **among tickets already judged same-error/relevant**, not globally; older occurrences are still cited; tuned on the golden set.
- **`created_at` parse fragility** (format `"2024-08-22 6:37 AM"`, possibly missing) → bad/empty dates. Mitigated by a tolerant parser with graceful fallback (no date line, never crash); tested.
- **"Smart-feel" synthesis is qualitative** → can't fully unit-test. Mitigated: deterministic tests assert the *prompt directive + dates + citations*; the live golden gate (both providers) judges actual synthesis quality before ship.
- **Ticket Project normalization mis-maps** a Project value → wrong product filter. Mitigated by an explicit mapping table + `other` fallback + keeping the raw `project` for display; tested.
- **Reindex cost** (~36 min full corpus) — run once at ship, same as v2.9.1.
- **Fusion bloats the prompt** slightly (restates the original question) — negligible vs. the scaffold; improves correctness.
