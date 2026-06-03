import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.ingest import ingest
from Dev.kb_chatbot.retriever import Retriever, Filters
from Dev.kb_chatbot.llm.fake_provider import FakeProvider
from Dev.kb_chatbot.chat.session import Session
from Dev.kb_chatbot.chat.orchestrator import handle_turn, Deps

FIX = Path(__file__).parent / "fixtures" / "tiny_library"
GOLDEN = json.loads((Path(__file__).parent / "fixtures" / "golden_qa.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def deps_factory():
    tmp = tempfile.mkdtemp()
    ingest(FIX, Path(tmp))

    def make(confidence_floor: float, fake_text: str):
        r = Retriever(Path(tmp), confidence_floor=confidence_floor)
        llm = FakeProvider(canned_text=fake_text)
        return Deps(retriever=r, llm=llm, usage_logger=lambda t: None)
    return make


@pytest.mark.parametrize("case", GOLDEN)
def test_golden_qa_case(deps_factory, case):
    must_titles = case.get("must_retrieve_any_of", [])
    fake_cite = ""
    if must_titles:
        fake_cite = f"[TradeDesk · dealing · {must_titles[0]}]"
    fake_text = f"Stub answer {fake_cite}"

    if case["expect"] == "abstain":
        deps = deps_factory(confidence_floor=0.99, fake_text="should never see this")
    else:
        deps = deps_factory(confidence_floor=0.0, fake_text=fake_text)

    session = Session.new()
    filters = Filters(**case.get("filters", {}))
    turn = handle_turn(case["user_msg"], session, filters,
                        "claude-haiku-4-5-20251001", deps=deps)

    if case["expect"] == "abstain":
        assert turn.kind == "abstain"
    elif case["expect"] == "clarify_or_answer":
        assert turn.kind in ("answer", "clarification", "abstain")
    else:
        assert turn.kind in ("answer", "clarification")