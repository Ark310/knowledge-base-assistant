# CLAUDE.md

Guidance for Claude Code when working in this repo.

## Layout
- `scraper/`: KB Scraper (Playwright, async engines, parsers, writers, Qt GUI). Tests are in `tests/`.
- `Dev/kb_chatbot/`: KB Chatbot (ingest, hybrid retrieval, orchestrator, providers, web UI). Tests are in `Dev/kb_chatbot/tests/`.
- `ai_pc/reasoning_gateway/`: on-prem Ollama + Caddy gateway scripts.
- `docs/superpowers/`: design specs and implementation plans, one pair per version.

## Working rules
- Every feature follows spec → plan → TDD tasks → review → live smoke. Write the spec and plan first.
- Run `python -m pytest -q` before committing. Use the fake LLM provider, never a real model, in tests.
- Never commit scraped content, tickets, indexes, eval dumps built from real queries, or fine-tuning data.
  Fixtures must be synthetic and PII-free.
- Ticket text must pass through `chat/ticket_redactor.redact(...)`, and the secret probe must report 0 leaks.
- Credentials live in the OS keyring only.

(During development this project also used OpenWolf, a `.wolf/` memory, bug log and anatomy map. That folder is not published.)
