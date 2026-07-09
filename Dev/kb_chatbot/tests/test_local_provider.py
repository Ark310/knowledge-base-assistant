import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest
from Dev.kb_chatbot.llm import local_provider as LP
from Dev.kb_chatbot.llm.local_provider import LocalProvider, LocalProviderError


def test_build_payload_prepends_system_and_flattens_multimodal():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": [
            {"type": "text", "text": "look at this"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "xxx"}},
        ]},
    ]
    p = LP._build_payload(msgs, "contoso-reasoning-qwen25-7b", "SYSTEM", 256)
    assert p["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert p["messages"][-1]["content"] == "look at this"     # image dropped, text kept
    assert p["temperature"] == 0 and p["seed"] == 42 and p["stream"] is False
    assert p["model"] == "contoso-reasoning-qwen25-7b"


def test_chat_returns_llmresponse(monkeypatch):
    def fake_post(url, headers, payload):
        assert url.endswith("/chat/completions")
        assert headers["Authorization"].startswith("Basic ")
        return {"choices": [{"message": {"content": "the answer"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 5}}
    monkeypatch.setattr(LP, "_post_json", fake_post)
    prov = LocalProvider("http://x:11500/v1", "abdul", "pw")
    r = prov.chat(messages=[{"role": "user", "content": "q"}],
                  model="contoso-reasoning-qwen25-7b", system_prompt="SYS", max_tokens=128)
    assert r.text == "the answer"
    assert r.input_tokens == 12 and r.output_tokens == 5
    assert r.cost_estimate_usd == 0.0


def test_missing_password_raises():
    with pytest.raises(LocalProviderError):
        LocalProvider("http://x:11500/v1", "abdul", None)


def test_http_error_raises(monkeypatch):
    def boom(url, headers, payload):
        raise OSError("connection refused")
    monkeypatch.setattr(LP, "_post_json", boom)
    prov = LocalProvider("http://x:11500/v1", "abdul", "pw")
    with pytest.raises(LocalProviderError):
        prov.chat(messages=[{"role": "user", "content": "q"}],
                  model="contoso-reasoning-qwen25-7b", system_prompt="SYS")


def test_bad_shape_raises(monkeypatch):
    monkeypatch.setattr(LP, "_post_json", lambda u, h, p: {"unexpected": True})
    prov = LocalProvider("http://x:11500/v1", "abdul", "pw")
    with pytest.raises(LocalProviderError):
        prov.chat(messages=[{"role": "user", "content": "q"}],
                  model="contoso-reasoning-qwen25-7b", system_prompt="SYS")
