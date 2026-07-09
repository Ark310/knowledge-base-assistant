"""Live smoke for the Local provider against the AI-PC gateway (operator-run).

Reads gateway URL + username from settings.json and the password from the keyring
(or --password). Never prints the password.

  python -m Dev.kb_chatbot.eval.local_smoke --base-url http://<ip>:11500/v1 --username abdul --password <pw>
"""
from __future__ import annotations
import argparse

from Dev.kb_chatbot.llm.local_provider import LocalProvider
from Dev.kb_chatbot.llm import local_creds
from Dev.kb_chatbot import settings as S


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="")
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    args = ap.parse_args()

    st = S.load_settings()
    base_url = args.base_url or st.reasoning_base_url
    username = args.username or st.reasoning_username
    password = args.password or local_creds.get_password(username)
    if not (base_url and username and password):
        raise SystemExit("Need base_url + username + password (settings/keyring or flags).")

    prov = LocalProvider(base_url, username, password)
    r = prov.chat(messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                  model="contoso-reasoning-qwen25-7b",
                  system_prompt="You are a test harness. Answer tersely.", max_tokens=32)
    print(f"OK response: {r.text!r}  ({r.input_tokens} in / {r.output_tokens} out, {r.latency_ms} ms)")
    # Determinism check: same question twice -> identical text (temp 0 + seed).
    r2 = prov.chat(messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                   model="contoso-reasoning-qwen25-7b",
                   system_prompt="You are a test harness. Answer tersely.", max_tokens=32)
    print("DETERMINISTIC" if r.text == r2.text else "WARN: non-deterministic output")


if __name__ == "__main__":
    main()
