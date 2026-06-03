import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pytest

from Dev.kb_chatbot.llm.claude_code_provider import (
    ClaudeCodeProvider, ClaudeCodeNotFoundError, _ensure_claude_available, _build_user_prompt,
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


def test_build_user_prompt_flattens_messages():
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "what's quick pay?"},
    ]
    out = _build_user_prompt(msgs)
    assert "USER: hello" in out
    assert "ASSISTANT: hi" in out
    assert out.endswith("USER: what's quick pay?")
