"""V2.3 per-turn pipeline. Retrieval-first -> confidence gate -> topic-drift detection ->
clarification fallback for borderline-score queries -> LLM call -> citation validation."""
from __future__ import annotations
import logging
import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chat.session import Session, Turn
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.citations import validate as validate_citations
from Dev.kb_chatbot.llm.base import LLMProvider
from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeNotFoundError
from Dev.kb_chatbot.prompt import build_system_prompt, build_messages
from Dev.kb_chatbot.retriever import Retriever, Filters

log = logging.getLogger("kb_chatbot.orchestrator")

ABSTAIN_MESSAGE = (
    "I haven't been trained on this — it's not in the knowledge base I have access to. "
    "Want to refine the question? Try naming a product (API, TradeDesk, SalesHub, Web2, Web4, Other), "
    "a related keyword, or a how-to topic."
)

_DRIFT_PREVIOUS_FLOOR = 0.50   # previous turn must have been confident
_DRIFT_CURRENT_CEILING = 0.20  # current turn must be very low

DRIFT_NOTE = "\n\n[TOPIC SHIFT: The user has changed topics. Treat this as a fresh question. Do not reference prior context.]"


def _is_topic_drift(previous: float, current: float) -> bool:
    return previous >= _DRIFT_PREVIOUS_FLOOR and current < _DRIFT_CURRENT_CEILING


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


def handle_turn(user_msg: str, session: Session, filters: Filters,
                default_model: str, *, deps: Deps) -> Turn:
    history = session.history_for_llm(config.MAX_HISTORY_TURNS)
    session.add_user(user_msg)

    result = deps.retriever.retrieve(user_msg, filters)

    # Topic-drift: inject note if confidence dropped sharply from previous turn
    drift_note = ""
    if _is_topic_drift(session.last_rerank_score, result.rerank_top_score):
        drift_note = DRIFT_NOTE
    session.last_rerank_score = result.rerank_top_score

    if not result.abstain_reason:
        if not (filters.product or _mentions_product(user_msg) or _recent_product_in_history(session)):
            quick = deps.retriever.retrieve_quick(user_msg, limit=10)
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
        turn = Turn(
            role="assistant",
            content=vr.stripped_text,
            kind="answer",
            citations=[{"raw": c.raw, "verified": True} for c in vr.verified]
                      + [{"raw": c.raw, "verified": False} for c in vr.unverified],
            retrieved_ids=[c.id for c in result.chunks],
            model=resp.model,
            tokens_in=resp.input_tokens,
            tokens_out=resp.output_tokens,
            latency_ms=resp.latency_ms,
        )
        session.add(turn)
        deps.usage_logger(turn)
        return turn

    if result.rerank_top_score > config.CLARIFY_SCORE_FLOOR and not (
        filters.product or _mentions_product(user_msg) or _recent_product_in_history(session)
    ):
        quick = deps.retriever.retrieve_quick(user_msg, limit=10)
        if _needs_clarification_from_quick(quick):
            clar_fn = deps.clarifier or _default_clarifier
            turn = Turn(role="assistant", content=clar_fn(user_msg, quick),
                        kind="clarification", retrieved_ids=[c.id for c in quick])
            session.add(turn)
            deps.usage_logger(turn)
            return turn

    turn = Turn(role="assistant", kind="abstain", content=ABSTAIN_MESSAGE)
    session.add(turn)
    deps.usage_logger(turn)
    return turn