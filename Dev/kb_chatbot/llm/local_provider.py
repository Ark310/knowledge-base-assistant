"""LocalProvider: the on-prem fine-tuned model behind the AI-PC gateway.

OpenAI-compatible POST to <base_url>/chat/completions with HTTP Basic auth.
Deterministic (temperature 0 + fixed seed). Text-only: image blocks are dropped
(the local model is a text model). No provider API key - LAN Basic-auth only."""
from __future__ import annotations
import base64
import json
import logging
import time
import urllib.request
from typing import Optional

from Dev.kb_chatbot.llm.base import LLMProvider, LLMResponse, estimate_cost

log = logging.getLogger("kb_chatbot.llm.local")

_TIMEOUT_S = 180
_SEED = 42


class LocalProviderError(RuntimeError):
    """Local gateway unreachable / unauthorized / bad response / missing creds."""


def _flatten(content) -> str:
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    return str(content)


def _build_payload(messages: list[dict], model: str, system_prompt: str, max_tokens: int) -> dict:
    out = [{"role": "system", "content": system_prompt}]
    for m in messages:
        out.append({"role": m.get("role", "user"), "content": _flatten(m.get("content", ""))})
    return {"model": model, "messages": out, "temperature": 0, "seed": _SEED,
            "stream": False, "max_tokens": max_tokens}


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


class LocalProvider(LLMProvider):
    def __init__(self, base_url: str, username: str, password: Optional[str]) -> None:
        if not base_url or not username or not password:
            raise LocalProviderError(
                "Local model not configured. Set the gateway URL + username in Settings "
                "and enter the password (stored in the OS keyring).")
        self.base_url = base_url.rstrip("/")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._headers = {"Authorization": f"Basic {token}", "Content-Type": "application/json"}

    def warm_up(self, system_prompt: str, model: str) -> None:
        pass  # first request wakes the model (Ollama loads on demand)

    def chat(self, *, messages, model, system_prompt, max_tokens: int = 1024) -> LLMResponse:
        started = time.time()
        url = f"{self.base_url}/chat/completions"
        payload = _build_payload(messages, model, system_prompt, max_tokens)
        try:
            body = _post_json(url, self._headers, payload)
        except Exception as exc:
            raise LocalProviderError(f"Local gateway request failed: {type(exc).__name__}") from exc
        try:
            text = (body["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LocalProviderError("Local gateway returned an unexpected response shape") from exc
        usage = body.get("usage") or {}
        tin = int(usage.get("prompt_tokens", 0) or 0)
        tout = int(usage.get("completion_tokens", 0) or 0)
        if not tin and not tout:
            tin = max(1, len(system_prompt) // 4)
            tout = max(1, len(text) // 4)
        return LLMResponse(
            text=text, input_tokens=tin, output_tokens=tout, model=model,
            latency_ms=int((time.time() - started) * 1000),
            cost_estimate_usd=estimate_cost(model, tin, tout),
        )
