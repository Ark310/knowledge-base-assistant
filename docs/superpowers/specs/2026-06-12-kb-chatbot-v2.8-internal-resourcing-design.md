# KB Chatbot v2.8 — Internal Tool: Team Resourcing, Client Context & Ticket/KB References — Design Spec

**Date:** 2026-06-12
**Status:** Approved (design); pending spec review → implementation plan
**Builds on:** v2.7 (incremental indexing, fast startup, Codex gpt-5.4, versioned exe).

---

## 1. Context & Problem

The chatbot is now an **internal-only** tool. v2.6 redaction was built for a hypothetical external audience and strips everything — staff, client, names. Internally, support engineers want the bot to also:

1. Recommend **who to ask** about a specific issue/topic (CSQA owner first, then assignee/QA, then staff who handled it).
2. Name the **client** an issue occurred at, when asked.
3. **Cite the ticket** behind resolution steps — linking to the actual ticket page.
4. Link relevant **KB articles** (how-tos / topics / release notes) in steps where available.
5. Escalate to a **team lead / senior resource** when the bot doesn't know.

This must happen **without** weakening the guarantee that external **customer personal PII** (their emails/phones/personal names) and any **secrets/passwords/API keys** are never surfaced.

## 2. Goals

- On-demand team resourcing, client disclosure, and escalation — driven by clean ticket fields.
- Ticket citations point to the actual ticket; KB-article links included in steps where present.
- Customer-individual PII and secrets remain redacted (unchanged safety net).

## 3. Non-Goals

- No scraper changes (all fields already scraped).
- No retrieval-engine changes to *guarantee* KB articles surface for ticket queries (best-effort: link what's retrieved).
- No change to the KB-article (non-ticket) chunking or the Claude/Codex providers.
- v3 retrieval overhaul stays parked.

## 4. Locked Decisions (from brainstorming)

| Topic | Decision |
|---|---|
| Disclosure boundary | Surface internal Contoso staff + the **client company name**. Still redact external customer personal PII (emails/phones/personal names) + all secrets/passwords/API keys. |
| Resource identity | **Usernames as-is** (e.g. `p.shah`). No name/role mapping in v2.8. |
| When to surface | **On-demand only** — team/client/resourcing appear only when the user asks. |
| Resource priority | **CSQA owner → assignee/sqa_assignee/QA sign-offs → staff commenters**; if none/unknown → escalate to a team lead / senior resource. |
| Multi-ticket pick | **Most-frequent owner across the relevant retrieved tickets**, with ticket refs. |
| Ticket-ref style | **Inline `(Ticket #N)` on ticket-specific steps + a `Sources:` line.** |
| Ticket link target | The **actual ticket** (`edit_bug.aspx?id=N`), not the resolution page. |
| KB links in steps | Where a step maps to a KB article present in retrieved context, link it `[Title](url)`. |
| `created_by` | **Excluded** from resourcing — it is often the external requester (e.g. ticket #40000 `created_by=jhatwell` = the customer), so never offered as a go-to. |

## 5. Approach

**Field-derived surfacing + unchanged body redaction (Approach A).** Surface staff/client from the *structured ticket fields* (clean usernames + org), added to the chunk text and metadata. The body's customer-PII/secret redaction is left intact as the safety guarantee. The LLM does the on-demand resourcing/frequency ranking from the owner lines visible in the retrieved chunks — no separate code path or intent classifier.

*Rejected:* (B) inverting the redactor to an internal allowlist in the body — security-risky, large change to the audited redactor, unnecessary because resourcing comes from fields. (C) a deterministic code resourcing engine — needs intent detection + a separate retrieval/aggregation path; overkill for a small retrieved set.

## 6. Detailed Design

### 6.1 Ticket chunk — `Dev/kb_chatbot/ticket_ingest.py`
Prepend a structured, **un-redacted, field-derived** header to each ticket chunk's text:
```
Ticket #<id> — <safe_title>
Client: <organization>
CSQA owner: <csqa_owner> · Assignee: <assignee> · QA sign-off: <sqa_assignee, site1_qa_signoff, site2_qa_signoff (deduped, non-empty)> · Handled by: <staff comment authors + internal email-sender usernames, deduped>
Problem: <redacted problem>
Resolution: <resolution>
```
- All header values come straight from ticket fields (no body parsing), so they never carry customer-individual PII.
- Empty fields are omitted from the line.
- "Handled by" = `comments[].author` for `type=="comment"` **plus** the `by <username>` sender parsed from internal (contoso) email headers; deduped; `created_by` excluded.

Chunk **metadata** gains scalar fields for traceability/aggregation: `organization`, `csqa_owner`, `assignee`, `handled_by` (comma-joined). Existing `kind="ticket"`, `product`, `category`, `ticket_id`, `chunk_index` stay.

**Citation URL change:** set chunk `url` = `data["url"]` (the ticket page, `edit_bug.aspx?id=N`); keep `resolution_url` in metadata separately. The citation validator matches against the chunk's `url`, so `[Ticket #N](<ticket url>)` validates.

### 6.2 Redaction — `Dev/kb_chatbot/chat/ticket_redactor.py` + `ticket_ingest.py`
- **Stop redacting the client company name:** remove `organization` from the body's `known_terms` so the client name reads consistently in the Problem/Resolution text (it's already surfaced in the header). This is the only relaxation.
- **Unchanged (the safety net):** external customer emails, phones, personal names (greeting/action/display-name patterns), `@mentions`, and all credential/secret patterns continue to be stripped from the body.
- The structured header is built from fields and is **not** passed through `redact()` — but it only ever contains org + staff usernames, never customer-individual PII.

### 6.3 System prompt — `Dev/kb_chatbot/prompt.py`
Add rules (on-demand, do not volunteer in normal answers):
- **Resourcing (only when asked who to ask / who handled X):** recommend the **most-frequent CSQA owner across the relevant retrieved tickets** first, then assignee/QA sign-offs, then staff commenters; name them by username with ticket refs. If no owner/unknown → "consult a team lead / senior resource."
- **Client (only when asked which client):** name the `organization` from the relevant ticket(s); if unknown → escalate to a lead.
- **Privacy floor:** never disclose external customer personal contact details (names/emails/phones) or secrets/passwords/API keys, even though this is an internal tool.
- **Ticket references:** cite `(Ticket #N)` inline on steps drawn from a specific ticket, and end with a `Sources: #N, #M` line; ticket links target the actual ticket page.
- **KB links:** where a step maps to a KB how-to / topic / release-note present in the retrieved context, link it `[Title](url)` alongside the step.

### 6.4 Reindex correctness — `Dev/kb_chatbot/ingest.py`
Add `CHUNK_SCHEMA_VERSION` (constant) written into `index_manifest.json`. On ingest, if the manifest's stored value differs from the current constant, force a full rebuild (same path as `force_rebuild`/embed-model-change), so changed *chunking logic* (not just changed source files) re-embeds. Bump it for v2.8 so the new structured ticket chunks replace the old ones.

### 6.5 Version — `config.APP_VERSION = "2.8"`
Window title `Contoso KB Chatbot v2.8`; exe `ContosoKBChatbot-v2.8.exe` (`.spec` already reads `APP_VERSION`). Rebuild + re-ship the rebuilt index.

## 7. Testing

- **Redactor (`test_ticket_redactor`)**: keep all existing assertions that customer emails, phones, personal names, and secrets/credentials are stripped from the body. Add: a company/org name supplied as the ticket `organization` is **preserved** (it is no longer added to the redaction term list).
- **Ticket ingest (`test_ticket_ingest`)**: chunk text contains the structured header (`Client:`, `CSQA owner:`, `Handled by:`); metadata has `organization`/`csqa_owner`/`assignee`/`handled_by`; chunk `url` is the **ticket** URL (not resolution); `created_by` does **not** appear in `handled_by`; a ticket with no staff comment still skipped.
- **Schema-version guard (`test_ingest`)**: bumping `CHUNK_SCHEMA_VERSION` in the manifest forces a full re-embed (mirrors the embed-model-change test).
- **Full-corpus re-probe**: asserts **zero** external customer emails/phones/secrets leak across all ticket chunks (header + body), while explicitly *allowing* org names and internal staff usernames.

## 8. Verification before build (standing rule)

1. Full reindex from source (force, via schema bump); confirm ticket chunks carry the structured header + ticket URLs.
2. Source-run scenarios: (a) how-to → steps + `(Ticket #N)` + KB links where present; (b) "who should I ask about X" → most-frequent CSQA owner first + escalation; (c) "which client" → org name; (d) "customer email?" → declined; (e) unknown topic → escalate to lead.
3. Re-probe full corpus: external PII/secrets leaky = 0.
4. Only then bump version, rebuild exe, re-ship index; confirm in the exe.

## 9. Risks

- **PII leak via the structured header** — mitigated: header is field-only (org + staff usernames), never body-derived; full-corpus probe gates it.
- **`created_by` ambiguity** — excluded from resourcing to avoid surfacing an external requester as a go-to.
- **LLM frequency ranking is not deterministic** — bounded to the retrieved ticket set and is a recommendation, not an authority; acceptable.
- **KB links best-effort** — if retrieval doesn't surface a relevant KB article, no link appears; not a regression.
