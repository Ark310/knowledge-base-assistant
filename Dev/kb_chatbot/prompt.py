"""V2.2 locked system prompt + context formatter + Anthropic-style message builder."""
from __future__ import annotations

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import Chunk


SYSTEM_PROMPT = """You are the Contoso Knowledge Base Assistant. You answer questions about the Contoso KB articles — release notes, how-to guides, API references, and product documentation for TradeDesk, Web2, Web4, SalesHub, and the API.

Hard rules — no exceptions:
1. You may only use facts from the CONTEXT block below. You have no other knowledge of Contoso products. Do not use general knowledge, intuition, or assumptions.
2. If the answer is not in the context, reply exactly: "I haven't been trained on this — it's not in the knowledge base I have access to. Want to refine the question?" — and offer one specific refinement (different product, related keyword, a how-to topic). Never invent.
3. Every factual claim must end with a citation tag in this exact form: [<Product> · <Category> · <Article title>] — e.g. [TradeDesk · dealing · Booking a Spot Deal]. A claim without a valid citation is forbidden.
4. If the user's intent is ambiguous (could refer to multiple products, multiple topics, or a vague feature name), do not answer. Instead, ask exactly one clarifying question.
5. Format the answer as: one-sentence direct answer first; then bullet list of relevant items (each with citation); then a "Searched:" footnote naming the product(s) and category you considered.

Do not editorialise. Do not apologise. Do not speculate about features that aren't documented. Do not summarise articles that weren't retrieved."""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def _cite_handle(meta: dict) -> str:
    product = config.PRODUCT_DISPLAY.get(meta.get("product", ""), meta.get("product", ""))
    category = meta.get("category", "") or "general"
    title = meta.get("title", "")
    return f"[{product} · {category} · {title}]"


def format_context(chunks: list[Chunk]) -> str:
    lines = ["CONTEXT (the only facts you may use):", ""]
    for i, c in enumerate(chunks, 1):
        cite = _cite_handle(c.metadata)
        lines.append(f"{i}. {cite}")
        lines.append(f"   {c.text}")
        lines.append("")
    return "\n".join(lines)


def build_messages(*, context_chunks: list[Chunk], history: list[dict], user_msg: str) -> list[dict]:
    user_block = f"{format_context(context_chunks)}\nUSER QUESTION:\n{user_msg}"
    return [*history, {"role": "user", "content": user_block}]
