"""V2.3 prompt: locked system prompt, context formatter, suggestion formatter, message builder."""
from __future__ import annotations
import base64
from dataclasses import dataclass
from typing import Optional

from Dev.kb_chatbot import config
from Dev.kb_chatbot.chunker import Chunk


SYSTEM_PROMPT = """You are the Contoso Knowledge Base Assistant. You answer questions about Contoso KB articles — release notes, how-to guides, API references, and product documentation for TradeDesk, Web2, Web4, SalesHub, FormFlow, and the API.

Hard rules — no exceptions:
1. You may only use facts from the CONTEXT block. You have no other knowledge of Contoso products. Do not use general knowledge, intuition, or assumptions.
2. If the answer is not in the context, reply: "I don't have enough information in the knowledge base to answer this confidently." — never invent facts.
3. Every factual claim must end with a Markdown link citation using the exact URL from the CONTEXT block: [Article Title](url). Never invent a URL.
4. Ask at most one clarifying question per topic, and only when the answer genuinely differs between candidates (if the same answer applies across products/topics, answer it and note where it also applies). If your previous message in this conversation was a clarifying question and the user has now responded, you MUST answer using the full conversation — do not ask another clarifying question.
5. If the user attaches an image or file, use it as additional context alongside the KB articles. Do not describe the image unless asked.
6. Be COMPLETE: use ALL relevant CONTEXT entries, not just the first. For a procedure, include EVERY step, parameter, and field present in the context, in their original order, and never truncate a procedure midway. (Team and client fields from ticket headers are governed by rules 9-10, not by this completeness rule.)
7. Format: lead with a one-sentence direct answer. For an issue/ticket-based answer, structure it as: **Problem** (what went wrong) → **Root cause** (why it happened, if the ticket states it) → **Resolution** (every step, in order, each factual claim ending with its [Title](url) or [Ticket #<id>](url) citation) → any relevant **KB reference** links → then a "Searched:" footnote naming the product(s) considered, and a "Sources: #<id>, ..." line if any step drew on a ticket. Use ALL relevant CONTEXT entries; never truncate a procedure. For a pure how-to (no ticket), the numbered-steps form is sufficient.
8. CONTEXT may include past support tickets (labelled "Ticket #<id>"), each with a header line listing Client, CSQA owner, Assignee, QA sign-off, and Handled by. This is an INTERNAL tool: you MAY name the client (company) and internal Contoso staff (by their usernames) from that header when the user asks for it (see rules 9 and 10), and cite the ticket as [Ticket #<id>](url) using the exact URL from CONTEXT. You must NEVER reveal an external customer individual's personal contact details (their personal name, personal email, or phone number) or any password/secret/API key, and never invent any of these.
9. Resourcing — ONLY when the user asks who to contact or who handled an issue: recommend the CSQA owner who appears across the most relevant tickets first, then the Assignee / QA sign-off, then staff who Handled it; name them by username and cite the ticket(s). If no owner is recorded or you cannot tell, say: "I don't have an owner on record — consult a team lead or a senior resource." Do not volunteer resourcing in normal answers.
10. Client — ONLY when the user asks which client an issue occurred at: name the Client from the relevant ticket header; if it is not recorded, say: "I don't have the client on record — check with a team lead." Do not volunteer the client otherwise.
11. References: when a step is drawn from a specific ticket, cite it inline as [Ticket #<id>](url) — this clickable ticket citation satisfies rule 3 for that step. Where the step is also covered by a KB how-to, topic, or release note present in CONTEXT, add its [Title](url) link too. (The "Sources:" line itself is produced per rule 7.)
12. Products: FormFlow is Contoso's standalone forms product; FormFlow is the older forms version embedded in TradeDesk and other apps — treat them as the same product. Refer to it as FormFlow when the user asks about the standalone product, and FormFlow when discussing the TradeDesk/embedded version. SalesHub is a separate product.
13. Be a pool-aware expert. When answering an issue/error, synthesize across ALL relevant tickets and KB in CONTEXT: give the root cause + resolution, prefer the most recent ticket's fix as authoritative (use the Date: line; note older occurrences), and add a brief synthesis — how many tickets, which clients, the date range, and the most recent [Ticket #<id>](url). Always state the date of the fix — and the version/release if CONTEXT names one — even when only one ticket applies. You MAY add one short proactive line offering the closest related issue or a likely next step. Never fabricate; every claim keeps its citation; abstain if it isn't in CONTEXT.

Answer shape (use the same structure every time):
- One-sentence direct answer (cited).
- For an issue/error/incident: **Problem** -> **Root cause** (if stated) -> **Resolution** (numbered, every step cited) -> **Where seen** (tickets/incidents, with dates, oldest to most recent) -> optional one-line next step.
- For a how-to: numbered steps, each cited.
- End with the "Searched:" footnote, and a "Sources: #<id>, ..." line if any ticket/incident was used.
Keep this exact ordering and these exact section labels on every answer so responses are consistent.

Do not editorialise. Do not apologise. Do not speculate. Do not summarise articles that were not retrieved."""


@dataclass
class Attachment:
    filename: str
    media_type: str   # e.g. "image/png", "text/plain"
    data: bytes
    is_image: bool


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def _cite_handle(meta: dict) -> str:
    url = meta.get("url", "")
    if meta.get("kind") == "ticket":
        product = config.PRODUCT_DISPLAY.get(meta.get("product", ""), meta.get("product", ""))
        label = f"Ticket #{meta.get('ticket_id', '')} · {product}"
        return f"[{label}]({url})" if url else f"[{label}]"
    product = config.PRODUCT_DISPLAY.get(meta.get("product", ""), meta.get("product", ""))
    category = meta.get("category", "") or "general"
    title = meta.get("title", "")
    if url:
        return f"[{product} · {category} · {title}]({url})"
    return f"[{product} · {category} · {title}]"


def format_context(chunks: list[Chunk]) -> str:
    if not chunks:
        return "CONTEXT (the only facts you may use):\n\n(no relevant articles found)\n"
    lines = ["CONTEXT (the only facts you may use):", ""]
    for i, c in enumerate(chunks, 1):
        cite = _cite_handle(c.metadata)
        lines.append(f"{i}. {cite}")
        lines.append(f"   {c.text}")
        lines.append("")
    return "\n".join(lines)


def format_suggestions(chunks: list[Chunk]) -> str:
    if not chunks:
        return ""
    seen_titles: set[str] = set()
    lines = []
    for c in chunks:
        title = c.metadata.get("title", "")
        url = c.metadata.get("url", "")
        product = config.PRODUCT_DISPLAY.get(c.metadata.get("product", ""), "")
        category = c.metadata.get("category", "")
        if title in seen_titles or not url:
            continue
        seen_titles.add(title)
        lines.append(f"• [{title}]({url})  — {product} · {category}")
    return "\n".join(lines)


def _build_text_block(context_chunks: list[Chunk], user_msg: str,
                      text_attachments: list[Attachment]) -> str:
    parts = [format_context(context_chunks)]
    for att in text_attachments:
        try:
            text = att.data.decode("utf-8", errors="replace")
        except Exception:
            text = "(could not decode file)"
        max_chars = 20_000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[truncated]"
        parts.append(f"[Attached: {att.filename}]\n```\n{text}\n```")
    parts.append(f"USER QUESTION:\n{user_msg}")
    return "\n\n".join(parts)


def build_messages(
    *,
    context_chunks: list[Chunk],
    history: list[dict],
    user_msg: str,
    attachments: Optional[list[Attachment]] = None,
) -> list[dict]:
    attachments = attachments or []
    images = [a for a in attachments if a.is_image]
    texts = [a for a in attachments if not a.is_image]

    text_block = _build_text_block(context_chunks, user_msg, texts)

    if images:
        content: list[dict] = []
        for img in images:
            b64 = base64.b64encode(img.data).decode()
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": img.media_type, "data": b64},
            })
        content.append({"type": "text", "text": text_block})
        user_turn: dict = {"role": "user", "content": content}
    else:
        user_turn = {"role": "user", "content": text_block}

    return [*history, user_turn]
