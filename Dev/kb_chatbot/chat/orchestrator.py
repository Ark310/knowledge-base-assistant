"""V2.3 per-turn pipeline. Retrieval-first -> confidence gate -> topic-drift detection ->
clarification fallback for borderline-score queries -> LLM call -> citation validation."""
from __future__ import annotations
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chat.session import Session, Turn
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.citations import validate as validate_citations
from Dev.kb_chatbot.llm.base import LLMProvider
from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeNotFoundError
from Dev.kb_chatbot.prompt import build_system_prompt, build_messages, format_suggestions
from Dev.kb_chatbot.chat.ticket_redactor import scrub_answer
from Dev.kb_chatbot.retriever import Retriever, Filters, assemble_ticket

log = logging.getLogger("kb_chatbot.orchestrator")

ABSTAIN_MESSAGE = (
    "I haven't been trained on this — it's not in the knowledge base I have access to. "
    "Want to refine the question? Try naming a product (API, TradeDesk, SalesHub, FormFlow, Web2, Web4, Other), "
    "a related keyword, or a how-to topic."
)

OUT_OF_SCOPE_MESSAGE = (
    "That's outside the scope of the Contoso knowledge base — it covers the API, "
    "TradeDesk, SalesHub, FormFlow, Web2, Web4 and related product documentation and support tickets. "
    "If your question is about one of those, try naming the product and what you're trying to do."
)

ABSTAIN_WITH_SUGGESTIONS_TEMPLATE = """\
I don't have enough information in the knowledge base to answer this confidently.

Here are some articles that might be related — do any of these match what you're looking for?

{suggestions}

If none of these help, try rephrasing your question or use Learn Mode to add the missing information."""

LOW_CONFIDENCE_FOOTER = """\


---
*Not fully certain this covers your question. You might also check:*
{suggestions}"""

IMAGE_NOTE_TEMPLATE = (
    "\n\n📎 This ticket includes a screenshot that may hold additional detail not in the text — "
    "open the ticket to view it: [Ticket #{tid}]({url})"
)

SHORT_QUERY_CLARIFICATION = (
    "Could you give me a bit more context? For example, which product are you asking about "
    "(TradeDesk, API, Web2, Web4, SalesHub, or FormFlow) and what you're trying to do?"
)

_SHORT_QUERY_WORD_LIMIT = 4
LOW_CONFIDENCE_CEILING = 0.35   # 0-1 sigmoid: append suggestion footer below this


def _is_short_unspecified_query(text: str) -> bool:
    words = text.strip().split()
    if len(words) >= _SHORT_QUERY_WORD_LIMIT:
        return False
    return not _mentions_product(text)


_DRIFT_PREVIOUS_FLOOR = 0.85   # 0-1 sigmoid: previous turn was confident
_DRIFT_CURRENT_CEILING = 0.20  # 0-1 sigmoid: current turn very low

DRIFT_NOTE = "\n\n[TOPIC SHIFT: The user has changed topics. Treat this as a fresh question. Do not reference prior context.]"

CLARIFY_BRIDGE_NOTE = (
    "\n\n[CLARIFICATION ANSWERED — the user's original question was: \"{orig}\". "
    "They have now specified: \"{reply}\". Answer that original question directly "
    "using CONTEXT. Do NOT ask another clarifying question.]"
)


def _is_topic_drift(previous: float, current: float) -> bool:
    return previous >= _DRIFT_PREVIOUS_FLOOR and current < _DRIFT_CURRENT_CEILING


_FOLLOW_UP_WORD_LIMIT = 5


def _extract_single_product(text: str) -> Optional[str]:
    """Product slug if the text names exactly one product as a whole word, else None.
    Word boundaries matter: 'rapid' must not match 'api', 'another' must not match 'other'.
    Synonym-aware: resolves multi-word names (formflow, formflow, saleshub) via config."""
    low = text.lower()
    found = set()
    # multi-word synonyms first (e.g. "formflow", "saleshub")
    for name in ("formflow", "formflow", "formflow", "saleshub", "saleshub",
                 "tradedesk", "web2", "web4", "api", "other"):
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            slug = config.resolve_product(name)
            if slug:
                found.add(slug)
    return next(iter(found)) if len(found) == 1 else None


def _build_retrieval_query(session: Session, user_msg: str) -> tuple[str, Optional[str]]:
    """Fuse short replies with the prior question so retrieval sees full context.

    Returns (retrieval_query, extracted_product). Must be called BEFORE
    session.add_user(user_msg) so last_user_question() is the prior question.
    The raw user_msg is what the LLM sees; fusion affects retrieval only."""
    prev_q = session.last_user_question()
    if not prev_q:
        return user_msg, None
    if session.last_assistant_kind() == "clarification":
        return f"{prev_q} {user_msg}", _extract_single_product(user_msg)
    if len(user_msg.strip().split()) < _FOLLOW_UP_WORD_LIMIT:
        return f"{prev_q} {user_msg}", None
    return user_msg, None


def _mentions_product(text: str) -> bool:
    low = text.lower()
    if any(re.search(r"\b" + re.escape(p) + r"\b", low) for p in config.PRODUCTS):
        return True
    return any(syn in low for syn in ("formflow", "formflow", "saleshub"))


def _recent_product_in_history(session: Session) -> bool:
    for t in reversed(session.turns[-6:]):
        if _mentions_product(t["content"]):
            return True
    return False


def _needs_clarification_from_quick(quick: list[Chunk]) -> bool:
    if not quick:
        return False
    products = Counter(c.metadata.get("product", "") for c in quick)
    if len(products) <= 1:
        return False
    total = sum(products.values())
    dominant = products.most_common(1)[0][1]
    return dominant / total < 0.60


def _default_clarifier(user_msg: str, quick: list[Chunk]) -> str:
    products = sorted({c.metadata.get("product", "") for c in quick if c.metadata.get("product")})
    pretty = ", ".join(config.PRODUCT_DISPLAY.get(p, p) for p in products) or \
             "API, TradeDesk, SalesHub, FormFlow, Web2, Web4, or Other"
    return (f"Multiple products have records related to your question. "
            f"Which one are you asking about — {pretty}?")


from Dev.kb_chatbot.chat.query_rewriter import REWRITE_MODEL as _REWRITE_MODEL_NAME

_ERROR_RE = re.compile(
    r"\b(error|errors|issue|issues|fail(?:s|ed|ing|ure)?|null|exception|crash(?:e[ds])?|"
    r"bug|broken|wrong|incorrect|discrepan\w*|duplicat\w*|missing|not working|doesn'?t|"
    r"cannot|can'?t|unable)\b", re.IGNORECASE)


def _looks_like_error(query: str) -> bool:
    return bool(_ERROR_RE.search(query or ""))


# Explicit ticket references only ("ticket 75919", "bug #75919", "#75919") — pinned
# into context by ticket_id. A bare number is NOT treated as a ticket id: support
# tickets share the 5-digit space with amounts/quantities, so a prefix is required.
_TICKET_ID_RE = re.compile(r"(?:ticket|tickets|bug|#)\s*#?\s*(\d{3,7})", re.IGNORECASE)
# Words that signal a follow-up referring back to the tickets just discussed.
_FOLLOWUP_HINT = re.compile(
    r"\b(this|that|these|those|it|its|they|them|their|same|above|prior|previous|"
    r"who|owner|owned|handle[ds]?|handling|work(?:s|ed|ing)?|assigned|assignee|"
    r"client|escalat\w*|contact|resource|sign[\s-]?off)\b", re.IGNORECASE)


def _extract_ticket_ids(text: str) -> list[str]:
    out: list[str] = []
    for m in _TICKET_ID_RE.finditer(text):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def _is_reference_followup(text: str) -> bool:
    return (len(text.strip().split()) < _FOLLOW_UP_WORD_LIMIT
            or bool(_FOLLOWUP_HINT.search(text)))


def _expand_ticket_chunks(chunks: list[Chunk], retriever) -> list[Chunk]:
    """Replace each ticket fragment with the full assembled ticket (parent-document
    retrieval). One assembled chunk per ticket_id, kept at the position of first
    occurrence; non-ticket chunks are left untouched; order is otherwise preserved."""
    out: list[Chunk] = []
    seen_tickets: set[str] = set()
    for c in chunks:
        tid = c.metadata.get("ticket_id") if c.metadata.get("kind") == "ticket" else None
        if not tid:
            out.append(c)
            continue
        if tid in seen_tickets:
            continue
        seen_tickets.add(tid)
        siblings = retriever.get_by_ticket_ids([tid]) or [c]
        out.append(assemble_ticket(siblings))
    return out


def _ensure_tickets_alongside(query: str, chunks: list[Chunk], retriever) -> list[Chunk]:
    """If the context is KB-only for an error question, attach the best ticket
    (errors live on tickets too). Best-effort; reuses retrieve_quick."""
    has_kb = any(c.metadata.get("kind") != "ticket" for c in chunks)
    has_ticket = any(c.metadata.get("kind") == "ticket" for c in chunks)
    if not has_kb or has_ticket:
        return chunks
    seen = {c.id for c in chunks}
    for cand in retriever.retrieve_quick(query, limit=10):
        if cand.metadata.get("kind") == "ticket" and cand.id not in seen:
            return [*chunks, cand]
    return chunks


def _add_related_tickets(chunks: list[Chunk], retriever, *, limit: int = 2) -> list[Chunk]:
    """Surface additional distinct tickets covering the same error as the first ticket
    in context — bridging old<->new. Recent-first by created_at; deduped by ticket_id."""
    tickets = [c for c in chunks if c.metadata.get("kind") == "ticket"]
    if not tickets:
        return chunks
    seed = tickets[0]
    have = {c.metadata.get("ticket_id") for c in tickets}
    cands = [c for c in retriever.retrieve_quick(
                 seed.metadata.get("title", "") + " " + seed.text[:200], limit=12)
             if c.metadata.get("kind") == "ticket" and c.metadata.get("ticket_id") not in have]
    # dedup by ticket_id, prefer most recent
    by_id: dict = {}
    for c in cands:
        tid = c.metadata.get("ticket_id")
        if tid and tid not in by_id:
            by_id[tid] = c
    extra = sorted(by_id.values(), key=lambda c: c.metadata.get("created_at", ""), reverse=True)[:limit]
    return [*chunks, *extra]


def _ensure_kb_alongside(query: str, chunks: list[Chunk], retriever) -> list[Chunk]:
    """If the context has a ticket but no KB article, attach the best-matching KB
    chunk (best-effort, 'if there is one'). Reuses the wide-net retrieve_quick."""
    has_ticket = any(c.metadata.get("kind") == "ticket" for c in chunks)
    has_kb = any(c.metadata.get("kind") != "ticket" for c in chunks)
    if not has_ticket or has_kb:
        return chunks
    seen = {c.id for c in chunks}
    for cand in retriever.retrieve_quick(query, limit=10):
        if cand.metadata.get("kind") != "ticket" and cand.metadata.get("url") \
                and cand.id not in seen:
            return [*chunks, cand]
    return chunks


def _merge_chunks(primary: list[Chunk], secondary: list[Chunk], *, limit: int) -> list[Chunk]:
    out: list[Chunk] = []
    seen: set[str] = set()
    for c in [*primary, *secondary]:
        if c.id in seen:
            continue
        seen.add(c.id)
        out.append(c)
        if len(out) >= limit:
            break
    return out


@dataclass
class Deps:
    retriever: Retriever
    llm: LLMProvider
    usage_logger: Callable[[Turn], None] = lambda t: None
    clarifier: Optional[Callable[[str, list[Chunk]], str]] = None
    attachments: list = field(default_factory=list)
    rewriter: Optional[Callable[[str, list], object]] = None
    on_progress: Callable[[str], None] = lambda stage: None


def handle_turn(user_msg: str, session: Session, filters: Filters,
                default_model: str, *, deps: Deps) -> Turn:
    history = session.history_for_llm(config.MAX_HISTORY_TURNS)
    retrieval_query, extracted_product = _build_retrieval_query(session, user_msg)
    fused = retrieval_query != user_msg
    if extracted_product and not filters.product:
        filters = Filters(product=extracted_product,
                          version_min=filters.version_min,
                          version_max=filters.version_max)
    answering_clarification = session.last_assistant_kind() == "clarification"
    original_q = session.last_user_question() if answering_clarification else ""
    session.add_user(user_msg)

    err_q = _looks_like_error(retrieval_query)
    result = deps.retriever.retrieve(retrieval_query, filters,
                                     top_k_rerank=(config.TOP_K_RERANK_ERROR if err_q else None))

    # Escalation: one stateless LLM rewrite when post-fusion retrieval abstains
    # and there is conversation context to rewrite from.
    if (result.abstain_reason and deps.rewriter is not None and history
            and result.rerank_top_score >= config.OUT_OF_SCOPE_FLOOR):
        deps.on_progress("rephrase")
        rw = deps.rewriter(user_msg, history)
        if rw is not None:
            deps.usage_logger(Turn(
                role="system", kind="rewrite", content=rw.query,
                model=getattr(rw, "model", "") or _REWRITE_MODEL_NAME,
                tokens_in=rw.tokens_in,
                tokens_out=rw.tokens_out, latency_ms=rw.latency_ms,
            ))
            retrieval_query = rw.query
            result = deps.retriever.retrieve(retrieval_query, filters,
                                             top_k_rerank=(config.TOP_K_RERANK_ERROR if err_q else None))

    # ── Context augmentation: explicit ticket-ID pins + carried conversation focus ──
    # The LLM may only use CONTEXT (rule 1), so a follow-up about the tickets just
    # discussed — or one naming a ticket # — must re-inject those chunks into CONTEXT.
    # Carry ONLY when fresh retrieval is weak: a confident NEW question stands on its
    # own and must not be polluted by a stale prior ticket, even if it has a hint word.
    fresh_confident = (not result.abstain_reason
                       and result.rerank_top_score >= LOW_CONFIDENCE_CEILING)
    pinned = deps.retriever.get_by_ticket_ids(_extract_ticket_ids(user_msg))
    carried: list[Chunk] = []
    if not fresh_confident and _is_reference_followup(user_msg) and session.last_context_ids:
        carried = deps.retriever.get_by_ids(session.last_context_ids)
    augment = _merge_chunks(pinned, carried, limit=config.TOP_K_RERANK)
    skip_clarify = False
    if augment:
        # Lead with the explicit/carried focus; only append fresh if it was confident
        # (don't dilute the focus with the weak matches that triggered the carry).
        fresh = result.chunks if fresh_confident else []
        result.chunks = _merge_chunks(augment, fresh, limit=config.TOP_K_RERANK)
        result.abstain_reason = None
        if not fresh_confident:
            result.rerank_top_score = max(result.rerank_top_score, 1.0)
        skip_clarify = True

    # Topic-drift: inject note if confidence dropped sharply from previous turn
    drift_note = ""
    if _is_topic_drift(session.last_rerank_score, result.rerank_top_score):
        drift_note = DRIFT_NOTE
    session.last_rerank_score = result.rerank_top_score

    if not result.abstain_reason:
        if not skip_clarify and not answering_clarification and not (filters.product or _mentions_product(user_msg) or _recent_product_in_history(session)):
            quick = deps.retriever.retrieve_quick(retrieval_query, limit=10)
            if _needs_clarification_from_quick(quick):
                clar_fn = deps.clarifier or _default_clarifier
                turn = Turn(role="assistant", content=clar_fn(user_msg, quick),
                            kind="clarification", retrieved_ids=[c.id for c in quick])
                session.add(turn)
                deps.usage_logger(turn)
                return turn

        result.chunks = _expand_ticket_chunks(result.chunks, deps.retriever)
        result.chunks = _ensure_kb_alongside(retrieval_query, result.chunks, deps.retriever)
        if _looks_like_error(retrieval_query):
            result.chunks = _ensure_tickets_alongside(retrieval_query, result.chunks, deps.retriever)
            result.chunks = _expand_ticket_chunks(result.chunks, deps.retriever)  # assemble any newly attached ticket
            result.chunks = _add_related_tickets(result.chunks, deps.retriever)
            result.chunks = _expand_ticket_chunks(result.chunks, deps.retriever)  # assemble related
        try:
            llm_user_msg = user_msg + drift_note
            if answering_clarification and original_q:
                llm_user_msg += CLARIFY_BRIDGE_NOTE.format(orig=original_q, reply=user_msg)
            messages = build_messages(
                context_chunks=result.chunks,
                history=history,
                user_msg=llm_user_msg,
                attachments=deps.attachments or [],
            )
            resp = deps.llm.chat(
                messages=messages,
                model=default_model,
                system_prompt=build_system_prompt(),
                max_tokens=config.ANSWER_MAX_TOKENS,
            )
        except ClaudeCodeNotFoundError as exc:
            turn = Turn(role="assistant", kind="abstain", content=str(exc))
            session.add(turn)
            deps.usage_logger(turn)
            return turn
        except Exception as exc:
            log.exception("LLM call failed")
            turn = Turn(role="assistant", kind="abstain",
                        content=f"Sorry — the LLM call failed: {exc}. Details in run.log.")
            session.add(turn)
            deps.usage_logger(turn)
            return turn

        vr = validate_citations(scrub_answer(resp.text), result.chunks)
        answer_text = vr.stripped_text
        # Footer fires for scores in [CONFIDENCE_FLOOR, LOW_CONFIDENCE_CEILING)
        if result.rerank_top_score < LOW_CONFIDENCE_CEILING:
            suggestion_block = format_suggestions(deps.retriever.suggest(retrieval_query, top_k=3))
            if suggestion_block:
                answer_text += LOW_CONFIDENCE_FOOTER.format(suggestions=suggestion_block)
        # Append screenshot note for the first used ticket chunk with images
        for c in result.chunks:
            if c.metadata.get("kind") == "ticket" and c.metadata.get("has_images") \
                    and c.metadata.get("url"):
                answer_text += IMAGE_NOTE_TEMPLATE.format(
                    tid=c.metadata.get("ticket_id", ""), url=c.metadata["url"])
                break
        turn = Turn(
            role="assistant",
            content=answer_text,
            kind="answer",
            citations=[{"raw": c.raw, "verified": True} for c in vr.verified]
                      + [{"raw": c.raw, "verified": False} for c in vr.unverified],
            retrieved_ids=[c.id for c in result.chunks],
            model=resp.model,
            tokens_in=resp.input_tokens,
            tokens_out=resp.output_tokens,
            latency_ms=resp.latency_ms,
            attachments=[a.filename for a in (deps.attachments or [])],
        )
        session.last_context_ids = [c.id for c in result.chunks]  # focus for follow-ups
        session.add(turn)
        deps.usage_logger(turn)
        return turn

    if result.rerank_top_score < config.OUT_OF_SCOPE_FLOOR:
        turn = Turn(role="assistant", kind="abstain", content=OUT_OF_SCOPE_MESSAGE)
        session.add(turn)
        deps.usage_logger(turn)
        return turn

    if result.rerank_top_score > config.CLARIFY_SCORE_FLOOR and not answering_clarification and not (
        filters.product or _mentions_product(user_msg) or _recent_product_in_history(session)
    ):
        quick = deps.retriever.retrieve_quick(retrieval_query, limit=10)
        if _needs_clarification_from_quick(quick):
            clar_fn = deps.clarifier or _default_clarifier
            turn = Turn(role="assistant", content=clar_fn(user_msg, quick),
                        kind="clarification", retrieved_ids=[c.id for c in quick])
            session.add(turn)
            deps.usage_logger(turn)
            return turn

    if not fused and _is_short_unspecified_query(user_msg):
        turn = Turn(role="assistant", kind="clarification",
                    content=SHORT_QUERY_CLARIFICATION)
        session.add(turn)
        deps.usage_logger(turn)
        return turn

    suggestion_block = format_suggestions(deps.retriever.suggest(retrieval_query, top_k=3))
    content = (ABSTAIN_WITH_SUGGESTIONS_TEMPLATE.format(suggestions=suggestion_block)
               if suggestion_block else ABSTAIN_MESSAGE)
    turn = Turn(role="assistant", kind="abstain", content=content)
    session.add(turn)
    deps.usage_logger(turn)
    return turn