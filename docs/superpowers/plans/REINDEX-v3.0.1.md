# v3.0.1 Reindex (operator runbook)

Phase 2 changed ticket ingestion and bumped `CHUNK_SCHEMA_VERSION` (4 -> 5), so the
index must be rebuilt once. Optionally re-scrape the live portal first for fresh
data + portal.contoso.example URLs.

## 1. (Optional) Re-scrape fresh tickets
Run the v4 ticket scraper against **portal.contoso.example** into `library/tickets/`
(needs portal login). Skip this if the on-disk tickets are already current — the
schema fix works on the existing files too, but their `url` may still be the old
support.contoso.example form until re-scraped.

## 2. Reindex from source (forces a clean re-embed via the schema bump)
```powershell
$py = "scraper\venv\Scripts\python.exe"
& $py -c "from pathlib import Path; from Dev.kb_chatbot import config; from Dev.kb_chatbot.ingest import ingest; print(ingest(Path('library'), config.CHROMA_DIR, force_rebuild=True))"
```
(Or use the app's Settings -> Reindex; the schema-version change forces a full
re-embed either way. Note live state now lives under `%LOCALAPPDATA%\ContosoKBChatbot`.)

## 3. Verify
- Ticket chunks carry `resolved` (bool) and, once re-scraped, `url` on
  `portal.contoso.example`. Unresolved tickets show `[UNRESOLVED]` in the chunk text.
- Run the secret/PII probe (scratchpad `_v291_secret_probe.py` style) over the rebuilt
  corpus and confirm `leaks=0` (real emails/secrets, not the `[redacted]` placeholder).

## 4. Smoke, then build
- In the app, ask a few error questions (both providers) and an FormFlow question;
  confirm citations resolve to `portal.contoso.example`, and that a "has this been seen
  before?" question surfaces relevant tickets (resolved and unresolved).
- Only then rebuild the exe (standing rule: smoke + operator confirmation before compile).
