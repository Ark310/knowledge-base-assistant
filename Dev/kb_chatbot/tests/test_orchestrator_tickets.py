import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.retriever import Filters, RetrievalResult
from Dev.kb_chatbot.llm.fake_provider import FakeProvider

URL = "https://support.contoso.example/edit_bug.aspx?id=75919"


def _frag(idx, body, has_images=False):
    text = "Ticket #75919 — GetWebDeal missing buy amount"
    if idx == 0:
        text += "\nClient: Acme · CSQA owner: p.shah"
    text += f"\n\n{body}"
    return Chunk(id=f"ticket_h:{idx}", text=text, metadata={
        "kind": "ticket", "ticket_id": "75919", "title": "Ticket #75919",
        "url": URL, "category": "api", "product": "tradedesk",
        "chunk_index": idx, "has_images": has_images})


# All three fragments of the ticket; retrieve() returns only the middle one.
_ALL = [_frag(0, "Problem: buy amount came back null"),
        _frag(1, "Root cause: the mapping dropped the field"),
        _frag(2, "Resolution: re-added the field and redeployed")]


class FragmentRetriever:
    """retrieve() surfaces ONLY chunk 1 (a fragment); get_by_ticket_ids returns all."""
    def __init__(self):
        self.captured = None
    def retrieve(self, query, filters):
        return RetrievalResult(chunks=[_ALL[1]], rerank_top_score=0.9)
    def get_by_ids(self, ids):
        return []
    def get_by_ticket_ids(self, tids):
        return list(_ALL) if "75919" in [str(t) for t in tids] else []
    def retrieve_quick(self, query, limit=10):
        return []
    def suggest(self, query, top_k=5):
        return []


def test_ticket_answer_sees_full_ticket_not_fragment():
    """The model must receive the WHOLE ticket (problem + root cause + resolution),
    even though retrieval only surfaced one fragment."""
    llm = FakeProvider(canned_text=f"ok [Ticket #75919]({URL})")
    d = Deps(retriever=FragmentRetriever(), llm=llm)
    turn = handle_turn("why did GetWebDeal return null buy amount",
                       Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "answer"
    # The single user message the LLM saw must contain all three fragment bodies.
    sent = llm.calls[-1]["messages"][-1]["content"]
    assert "buy amount came back null" in sent      # problem (chunk 0)
    assert "the mapping dropped the field" in sent   # root cause (chunk 1)
    assert "re-added the field and redeployed" in sent  # resolution (chunk 2)
    # ticket appears once in the retrieved set, not as 3 fragments
    assert turn.retrieved_ids.count("ticket_h:0") <= 1


def test_answer_uses_raised_max_tokens():
    from Dev.kb_chatbot import config
    llm = FakeProvider(canned_text=f"ok [Ticket #75919]({URL})")
    d = Deps(retriever=FragmentRetriever(), llm=llm)
    handle_turn("why did GetWebDeal return null buy amount",
                Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert llm.calls[-1]["max_tokens"] == config.ANSWER_MAX_TOKENS
    assert config.ANSWER_MAX_TOKENS >= 2048


def test_orchestrator_scrubs_answer_before_render():
    llm = FakeProvider(canned_text=f"resolved [Ticket #75919]({URL}) email leaked@acme.com")
    d = Deps(retriever=FragmentRetriever(), llm=llm)
    turn = handle_turn("why did GetWebDeal return null buy amount",
                       Session.new(), Filters(), "claude-haiku-4-5-20251001", deps=d)
    assert "leaked@acme.com" not in turn.content
