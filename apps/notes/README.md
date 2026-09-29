# notes

The admin's "save for later" store: links and text sent to the Telegram bot are saved at once,
enriched (title, author, caption, thumbnail), filed into Sections with a Russian Gist, and sorted
on a private web UI. Merged in from the standalone `maxi-notes` repo (ADR-015).

- Vocabulary: `CONTEXT.md` (separate from the repo glossary: **Source** means something else here)
- Decisions: `docs/decisions/0001–0006` · Spec: `docs/spec.md` · Tickets: `docs/tickets/`

## Layout

| Where | What |
|---|---|
| `apps/notes/src/notes/` | domain (`domain/`), sqlite store (`db.py`), Enrichment (`enrich/`), Classifier port (`classify/`), `sweeper.py`, `smoke.py` |
| `interfaces/telegram_bot/…/handlers/documents.py` | the admin's ask-first card (`admin_input_handler`, 💾 on the price card) |
| `interfaces/telegram_bot/…/handlers/notes.py` | 💾 saving, the 🤖 and ↩️ buttons, background enrichment and the sweeper |
| `interfaces/telegram_bot/…/notes_ui.py` | Acknowledgement text and keyboard (Russian) |
| `interfaces/notes_web/` | the web UI (`notes-web`) |

## Run

```bash
uv run notes-smoke https://youtu.be/dQw4w9WgXcQ   # fetch + file one input, print the result
uv run notes-smoke http://169.254.169.254/         # the SSRF guard refuses it
uv run telegram-bot                                # 💾 on the card for ADMIN_TELEGRAM_ID
uv run notes-web                                   # http://127.0.0.1:8082
```

Both processes share the sqlite file at `NOTES_DB_PATH` (WAL mode). The schema and the starter
Sections are created on first start.

| Variable | Default | Meaning |
|---|---|---|
| `NOTES_DB_PATH` | `data/notes.sqlite3` | sqlite location (compose pins `/data/notes.sqlite3`) |
| `NOTES_ENRICH_SWEEP_SECONDS` | `60` | retry / restart-leftover sweep interval |
| `NOTES_CLASSIFIER_PROVIDER` | `fake` | `openai` (Filing + Russian Gist, ~$0.002 an Item) or `fake` (offline, everything to Other) |
| `NOTES_CLASSIFIER_MODEL` | — | empty = `shared.pricing.DEFAULT_TRANSLATE_MODEL` |

## Status

Tickets 01–04 were done in maxi-notes: a Note on the web, deploy, Links with dedupe, and
Enrichment without an LLM. 05 (OpenAI Classifier) was done here. Next up are 06 (Filing keyboard), 07 (Browse),
08 (sorting pass on the web), 09 (Section management) and 10 (housekeeping). Their "(seam N)"
criteria predate the merge: check them by hand or with `notes-smoke`, since this repo has no
automated tests (ADR-001).
