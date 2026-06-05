"""V2.3 per-turn pipeline. Retrieval-first -> confidence gate -> topic-drift detection ->
clarification fallback for borderline-score queries -> LLM call -> citation validation."""
from __future__ import annotations
import logging
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
from Dev.kb_chatbot.retriever import Retriever, Filters

log = logging.getLogger("kb_chatbot.orchestrator")

ABSTAIN_MESSAGE = (
    "I haven't been trained on this — it's not in the knowledge base I have access to. "
    "Want to refine the question? Try naming a product (API, TradeDesk, SalesHub, Web2, Web4, Other), "
    "a related keyword, or a how-to topic."
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

SHORT_QUERY_CLARIFICATION = (
    "Could you give me a bit more context? For example, which product are you asking about "
    "(TradeDesk, API, Web2, Web4, or SalesHub) and what you're trying to do?"
)

_SHORT_QUERY_WORD_LIMIT = 4
LOW_CONFIDENCE_CEILING = 0.45


def _is_short_unspecified_query(text: str) -> bool:
    words = text.strip().split()
    if len(words) >= _SHORT_QUERY_WORD_LIMIT:
        return False
    return not _mentions_product(text)


_DRIFT_PREVIOUS_FLOOR = 0.50   # previous turn must have been confident
_DRIFT_CURRENT_CEILING = 0.20  # current turn must be very low

DRIFT_NOTE = "\n\n[TOPIC SHIFT: The user has changed topics. Treat this as a fresh question. Do not reference prior context.]"


def _is_topic_drift(previous: float, current: float) -> bool:
    return previous >= _DRIFT_PREVIOUS_FLOOR and current < _DRIFT_CURRENT_CEILING


_FOLLOW_UP_WORD_LIMIT = 5


def _extract_single_product(text: str) -> Optional[str]:
    """Product slug if the text names exactly one product, else None."""
    low = text.lower()
    found = [p for p in config.PRODUCTS if p in low]
    return found[0] if len(found) == 1 else None


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
    return any(p in low for p in config.PRODUCTS)


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
             "API, TradeDesk, SalesHub, Web2, Web4, or Other"
    return (f"Multiple products have records related to your question. "
            f"Which one are you asking about — {pretty}?")


@dataclass
class Deps:
    retriever: Retriever
    llm: LLMProvider
    usage_logger: Callable[[Turn], None] = lambda t: None
    clarifier: Optional[Callable[[str, list[Chunk]], str]] = None
    attachments: list = field(default_factory=list)


def handle_turn(user_msg: str, session: Session, filters: Filters,
                default_model: str, *, deps: Deps) -> Turn:
    history = session.history_for_llm(config.MAX_HISTORY_TURNS)
    retrieval_query, extracted_product = _build_retrieval_query(session, user_msg)
    fused = retrieval_query != user_msg
    if extracted_product and not filters.product:
        filters = Filters(product=extracted_product,
                          version_min=filters.version_min,
                          version_max=filters.version_max)
    session.add_user(user_msg)

    result = deps.retriever.retrieve(retrieval_query, filters)

    # Topic-drift: inject note if confidence dropped sharply from previous turn
    drift_note = ""
    if _is_topic_drift(session.last_rerank_score, result.rerank_top_score):
        drift_note = DRIFT_NOTE
    session.last_rerank_score = result.rerank_top_score

    if not result.abstain_reason:
        if not (filters.product or _mentions_product(user_msg) or _recent_product_in_history(session)):
            quick = deps.retriever.retrieve_quick(retrieval_query, limit=10)
            if _needs_clarification_from_quick(quick):
                clar_fn = deps.clarifier or _default_clarifier
                turn = Turn(role="assistant", content=clar_fn(user_msg, quick),
                            kind="clarification", retrieved_ids=[c.id for c in quick])
                session.add(turn)
                deps.usage_logger(turn)
                return turn

        try:
            messages = build_messages(
                context_chunks=result.chunks,
                history=history,
                user_msg=user_msg + drift_note,
                attachments=deps.attachments or [],
            )
            resp = deps.llm.chat(
                messages=messages,
                model=default_model,
                system_prompt=build_system_prompt(),
                max_tokens=1024,
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

        vr = validate_citations(resp.text, result.chunks)
        answer_text = vr.stripped_text
        # Footer fires for scores in [CONFIDENCE_FLOOR, LOW_CONFIDENCE_CEILING)
        if result.rerank_top_score < LOW_CONFIDENCE_CEILING:
            suggestion_block = format_suggestions(deps.retriever.suggest(retrieval_query, top_k=3))
            if suggestion_block:
                answer_text += LOW_CONFIDENCE_FOOTER.format(suggestions=suggestion_block)
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
        session.add(turn)
        deps.usage_logger(turn)
        return turn

    if result.rerank_top_score > config.CLARIFY_SCORE_FLOOR and not (
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