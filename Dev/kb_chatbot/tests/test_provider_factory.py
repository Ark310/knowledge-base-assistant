import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest
from Dev.kb_chatbot.llm import factory
from Dev.kb_chatbot.llm.local_provider import LocalProvider, LocalProviderError


class _S:
    reasoning_base_url = "http://x:11500/v1"
    reasoning_username = "abdul"


def test_make_local_provider(monkeypatch):
    monkeypatch.setattr(factory.local_creds, "get_password", lambda u: "pw")
    prov = factory.make_provider("local", settings=_S())
    assert isinstance(prov, LocalProvider)


def test_make_local_without_password_raises(monkeypatch):
    monkeypatch.setattr(factory.local_creds, "get_password", lambda u: None)
    with pytest.raises(LocalProviderError):
        factory.make_provider("local", settings=_S())


def test_make_fake_provider():
    from Dev.kb_chatbot.llm.fake_provider import FakeProvider
    assert isinstance(factory.make_provider("fake"), FakeProvider)


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        factory.make_provider("nope")
