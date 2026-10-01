# notes

The admin's "save for later" store: links, text, files and voice messages sent to the Telegram bot
are saved at once, enriched (title, author, caption, thumbnail, a voice's transcript), filed into Sections with a Russian Gist, and sorted
in the admin Mini App (ADR-016). Merged in from the standalone `maxi-notes` repo (ADR-015).

- Vocabulary: `CONTEXT.md` (separate from the repo glossary: **Source** means something else here)
- Decisions: `docs/decisions/0001–0008` · Spec: `docs/spec.md` · Tickets: `docs/tickets/`

## Layout

| Where | What |
|---|---|
| `apps/notes/src/notes/` | domain (`domain/`), sqlite store (`db.py`), Enrichment (`enrich/`), Classifier port (`classify/`), `sweeper.py`, `smoke.py` |
| `interfaces/telegram_bot/…/handlers/documents.py` | the admin's ask-first card (`admin_input_handler`, 💾 on the price card) |
| `interfaces/telegram_bot/…/handlers/notes.py` | 💾 saving, the 🤖 and ↩️ buttons, background enrichment and the sweeper |
| `interfaces/telegram_bot/…/notes_ui.py` | Acknowledgement text and keyboard (Russian) |
| `interfaces/telegram_bot/…/miniapp/` | the Mini App: notes API and UI (`telegram-miniapp`) |

## Run

```bash
uv run notes-smoke https://youtu.be/dQw4w9WgXcQ   # fetch + file one input, print the result
uv run notes-smoke --voice memo.ogg               # transcribe + file a voice file
uv run notes-smoke http://169.254.169.254/         # the SSRF guard refuses it
uv run telegram-bot                                # 💾 on the card for ADMIN_TELEGRAM_ID
uv run telegram-miniapp                            # http://127.0.0.1:8083, opened from Telegram
```

Both processes share the sqlite file at `NOTES_DB_PATH` (WAL mode). The schema and the starter
Sections are created on first start. The Mini App only accepts Telegram-signed requests, so
check it as in `docs/verifying.md` §2.

| Variable | Default | Meaning |
|---|---|---|
| `NOTES_DB_PATH` | `data/notes.sqlite3` | sqlite location (compose pins `/data/notes.sqlite3`) |
| `NOTES_ENRICH_SWEEP_SECONDS` | `60` | retry / restart-leftover sweep interval |
| `NOTES_CLASSIFIER_PROVIDER` | `fake` | `openai` (Filing + Russian Gist, ~$0.002 an Item) or `fake` (offline, everything to Other) |
| `NOTES_CLASSIFIER_MODEL` | — | empty = `shared.pricing.DEFAULT_TRANSLATE_MODEL` |

## Status

Tickets 01–04 were done in maxi-notes: a Note on the web, deploy, Links with dedupe, and
Enrichment without an LLM. 05 (OpenAI Classifier) was done here. 11 is the Mini App skeleton, 08
the sorting pass and 09 Section management in it (ADR-016). 06 (Filing keyboard) and 07 (Browse)
are replaced by the app. 12 (direct save + look at the content) was done after. 10 (housekeeping) is next. Their "(seam N)"
criteria predate the merge: check them by hand, with `notes-smoke` or with signed requests to the
Mini App API, since this repo has no automated tests (ADR-001).
