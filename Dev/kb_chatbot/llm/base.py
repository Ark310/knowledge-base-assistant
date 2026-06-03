"""Abstract LLM provider + shared cost-estimate helper."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

from Dev.kb_chatbot import config


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: int
    cost_estimate_usd: float


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price = config.COST_TABLE.get(model, {"in": 0.0, "out": 0.0})
    return (input_tokens / 1_000_000 * price["in"]) + (output_tokens / 1_000_000 * price["out"])


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, *, messages: list[dict], model: str, system_prompt: str,
             max_tokens: int = 1024) -> LLMResponse: ...
