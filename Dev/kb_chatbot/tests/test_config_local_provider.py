import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from Dev.kb_chatbot import config
from Dev.kb_chatbot import settings as S


def test_local_provider_registered():
    assert "local" in config.PROVIDERS
    assert config.PROVIDERS["local"]["default_model"] == "contoso-reasoning-qwen25-7b"
    assert config.default_model_for("local") == "contoso-reasoning-qwen25-7b"
    assert config.provider_of_model("contoso-reasoning-qwen25-7b") == "local"


def test_local_model_is_free_in_cost_table():
    assert config.COST_TABLE["contoso-reasoning-qwen25-7b"] == {"in": 0.0, "out": 0.0}


def test_settings_roundtrip_reasoning_fields(tmp_path):
    p = tmp_path / "settings.json"
    s = S.load_settings(p)
    s.reasoning_base_url = "http://192.0.2.50:11500/v1"
    s.reasoning_username = "abdul"
    S.save_settings(s, p)
    loaded = S.load_settings(p)
    assert loaded.reasoning_base_url == "http://192.0.2.50:11500/v1"
    assert loaded.reasoning_username == "abdul"
