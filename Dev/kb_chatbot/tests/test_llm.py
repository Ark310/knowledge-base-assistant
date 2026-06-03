import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot.llm.base import LLMResponse, LLMProvider
from Dev.kb_chatbot.llm.fake_provider import FakeProvider


def test_fake_provider_returns_canned_text():
    fp = FakeProvider(canned_text="hello world", input_tokens=10, output_tokens=5)
    r = fp.chat(messages=[{"role": "user", "content": "ignored"}],
                model="claude-haiku-4-5-20251001",
                system_prompt="sys")
    assert isinstance(r, LLMResponse)
    assert r.text == "hello world"
    assert r.input_tokens == 10
    assert r.output_tokens == 5
    assert r.cost_estimate_usd > 0


def test_fake_provider_cost_is_nonnegative_for_unknown_model():
    fp = FakeProvider(canned_text="x")
    r = fp.chat(messages=[{"role": "user", "content": "x"}],
                model="some-future-model",
                system_prompt="sys")
    assert r.cost_estimate_usd >= 0.0


def test_base_provider_is_abstract():
    import pytest
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore[abstract]
