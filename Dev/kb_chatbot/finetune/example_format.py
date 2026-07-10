"""Turn (retrieved chunks, question, answer) into a chat training record that
matches EXACTLY what orchestrator.handle_turn sends the local provider, so
training and inference see the same prompt."""
from __future__ import annotations
import json
from Dev.kb_chatbot.prompt import build_system_prompt, build_messages

def make_example(chunks, question: str, answer: str) -> dict:
    # build_messages([], user_msg) -> [user_turn]; reuse it for serving parity.
    user_turn = build_messages(context_chunks=chunks, history=[], user_msg=question)[-1]
    return {"messages": [
        {"role": "system", "content": build_system_prompt()},
        user_turn,
        {"role": "assistant", "content": answer},
    ]}

def dumps(example: dict) -> str:
    return json.dumps(example, ensure_ascii=False)

def loads(line: str) -> dict:
    return json.loads(line)
