import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps, CLARIFY_BRIDGE_NOTE
from Dev.kb_chatbot.chat.session import Session, Turn
from Dev.kb_chatbot.chunker import Chunk
from Dev.kb_chatbot.retriever import Filters, RetrievalResult
from Dev.kb_chatbot.llm.fake_provider import FakeProvider


def _kbchunk(title, url):
    return Chunk(id="k1", text="content",
                 metadata={"product": "tradedesk", "category": "dealing",
                           "title": title, "url": url})


class _R:
    """Confident retrieval so we reach the answer branch."""
    def retrieve(self, query, filters):
        return RetrievalResult(chunks=[_kbchunk("Drawdown", "https://help.contoso.example/dd")],
                               rerank_top_score=0.9)
    def get_by_ids(self, ids): return []
    def get_by_ticket_ids(self, tids): return []
    def retrieve_quick(self, query, limit=10): return []
    def suggest(self, query, top_k=5): return []


def test_answer_after_clarification_fuses_original_and_does_not_reclarify():
    llm = FakeProvider(canned_text="ok [Drawdown](https://help.contoso.example/dd)")
    d = Deps(retriever=_R(), llm=llm)
    s = Session.new()
    s.add_user("drawdown margin duplication on a full multi-line forward drawdown")
    s.add(Turn(
        role="assistant", kind="clarification", content="Which product? TradeDesk / Web2?"))
    turn = handle_turn("TD Client Server", s, Filters(),
                       "claude-haiku-4-5-20251001", deps=d)
    assert turn.kind == "answer"                       # did NOT re-clarify
    sent = llm.calls[-1]["messages"][-1]["content"]
    assert "drawdown margin duplication" in sent       # original question fused in
    assert "do not ask another clarifying question" in sent.lower()
