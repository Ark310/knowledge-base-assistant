"""Construct an LLMProvider from a provider id + settings."""
from __future__ import annotations
from typing import Optional

from Dev.kb_chatbot.llm.base import LLMProvider
from Dev.kb_chatbot.llm import local_creds


def make_provider(provider_id: str, settings: Optional[object] = None) -> LLMProvider:
    if provider_id == "claude":
        from Dev.kb_chatbot.llm.claude_code_provider import ClaudeCodeProvider
        return ClaudeCodeProvider()
    if provider_id == "openai":
        from Dev.kb_chatbot.llm.codex_provider import CodexProvider
        return CodexProvider()
    if provider_id == "local":
        from Dev.kb_chatbot.llm.local_provider import LocalProvider
        base_url = getattr(settings, "reasoning_base_url", "") if settings else ""
        username = getattr(settings, "reasoning_username", "") if settings else ""
        password = local_creds.get_password(username)
        return LocalProvider(base_url, username, password)
    if provider_id == "fake":
        from Dev.kb_chatbot.llm.fake_provider import FakeProvider
        return FakeProvider(canned_text="stub")
    raise ValueError(f"unknown provider: {provider_id}")
