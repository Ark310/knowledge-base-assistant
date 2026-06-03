"""Deterministic provider for tests; never touches the network."""
from __future__ import annotations
from Dev.kb_chatbot.llm.base import LLMProvider, LLMResponse, estimate_cost


class FakeProvider(LLMProvider):
    def __init__(self, canned_text: str = "(fake response)",
                 input_tokens: int = 100, output_tokens: int = 50,
                 latency_ms: int = 1):
        self.canned_text = canned_text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.latency_ms = latency_ms
        self.calls: list[dict] = []

    def chat(self, *, messages, model, system_prompt, max_tokens=1024) -> LLMResponse:
        self.calls.append({"messages": messages, "model": model,
                           "system_prompt": system_prompt, "max_tokens": max_tokens})
        return LLMResponse(
            text=self.canned_text,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            model=model,
            latency_ms=self.latency_ms,
            cost_estimate_usd=estimate_cost(model, self.input_tokens, self.output_tokens),
        )
