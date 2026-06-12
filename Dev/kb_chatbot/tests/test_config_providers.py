from Dev.kb_chatbot import config


def test_providers_have_claude_and_openai():
    assert set(config.PROVIDERS) == {"claude", "openai"}


def test_default_provider_is_claude():
    assert config.DEFAULT_PROVIDER == "claude"


def test_backward_compat_aliases():
    assert config.DEFAULT_MODEL == config.PROVIDERS["claude"]["default_model"]
    assert config.AVAILABLE_MODELS == config.PROVIDERS["claude"]["models"]


def test_every_model_has_cost_and_display():
    for prov in config.PROVIDERS.values():
        for model_id in prov["models"].values():
            assert model_id in config.COST_TABLE, f"{model_id} missing from COST_TABLE"
            assert model_id in config.MODEL_DISPLAY, f"{model_id} missing from MODEL_DISPLAY"


def test_openai_models_present():
    # Only gpt-5.4 works over Codex 0.139 with a ChatGPT account; gpt-5.5 and
    # gpt-5.4-mini 400 on the built-in `_search` tool schema. See config.PROVIDERS.
    ids = set(config.PROVIDERS["openai"]["models"].values())
    assert ids == {"gpt-5.4"}


def test_openai_costs():
    assert config.COST_TABLE["gpt-5.5"] == {"in": 5.00, "out": 30.00}
    assert config.COST_TABLE["gpt-5.4"] == {"in": 2.50, "out": 15.00}
    assert config.COST_TABLE["gpt-5.4-mini"] == {"in": 0.75, "out": 4.50}


def test_models_for():
    assert config.models_for("openai") == config.PROVIDERS["openai"]["models"]
    assert config.models_for("nope") == config.PROVIDERS["claude"]["models"]


def test_default_model_for():
    assert config.default_model_for("openai") == "gpt-5.4"
    assert config.default_model_for("claude") == "claude-sonnet-4-6"


def test_provider_of_model():
    assert config.provider_of_model("gpt-5.4") == "openai"
    assert config.provider_of_model("claude-sonnet-4-6") == "claude"
    assert config.provider_of_model("mystery") is None


def test_gui_settings_dialog_persists_provider():
    import inspect
    from Dev.kb_chatbot import gui
    src = inspect.getsource(gui.SettingsDialog.values)
    assert "default_provider=" in src


def test_gui_has_provider_factory_and_dropdown():
    import inspect
    from Dev.kb_chatbot import gui
    assert hasattr(gui, "build_provider")
    src = inspect.getsource(gui.MainWindow._build_ui)
    assert "AI Provider" in src


def test_token_usage_dialog_uses_shared_display_map():
    import inspect
    from Dev.kb_chatbot import gui
    src = inspect.getsource(gui.TokenUsageDialog)
    assert "config.MODEL_DISPLAY" in src
    assert "_MODEL_DISPLAY" not in src  # the hardcoded dict is gone
