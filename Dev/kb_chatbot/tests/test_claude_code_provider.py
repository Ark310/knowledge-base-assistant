import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.llm.claude_code_provider import (
    ClaudeCodeProvider, ClaudeCodeNotFoundError, _ensure_claude_available,
    _latest_user_content, _flatten_content,
)


def test_raises_when_claude_cli_missing(monkeypatch):
    from Dev.kb_chatbot.llm import claude_code_provider as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    with pytest.raises(ClaudeCodeNotFoundError) as excinfo:
        ClaudeCodeProvider()
    assert "Claude Code CLI not found" in str(excinfo.value)


def test_ensure_returns_path_when_present(monkeypatch):
    from Dev.kb_chatbot.llm import claude_code_provider as mod
    monkeypatch.setattr(mod.shutil, "which", lambda name: r"C:\fake\bin\claude.exe")
    assert _ensure_claude_available() == r"C:\fake\bin\claude.exe"


def test_latest_user_content_returns_last_user():
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "what's quick pay?"},
    ]
    out = _latest_user_content(msgs)
    assert "what's quick pay?" in out
    assert "hello" not in out


def test_flatten_content_str_passthrough():
    assert _flatten_content("hello world") == "hello world"


def test_flatten_content_list():
    content = [
        {"type": "image", "source": {}},
        {"type": "text", "text": "describe this"},
    ]
    assert _flatten_content(content) == "describe this"
