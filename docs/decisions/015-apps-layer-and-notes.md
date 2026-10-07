# ADR-015: An `apps/` layer, and Notes merged in from maxi-notes

Status: Accepted (2026-09-29). Amended 2026-09-29: decision 3's `notes-web` sorting UI is replaced by the Mini App (ADR-016). Amended 2026-10-07: notes keeps one Status (`todo` / `done`) and no Placement (notes ADR-0010).

## Context

`maxi-notes` was a separate repo: a single-owner "save for later" store with its own
Telegram bot, a sorting web UI and one sqlite file, deployed as a second compose stack on
this droplet. The owner wanted one bot and one codebase.

Notes does not fit the job contract (ADR-012). A workflow turns a source into a priced
deliverable once. Notes keeps state: Items, Sections, Status, Placement, background
enrichment with retries, and a web UI over it. Forcing it into `workflows/*` would break
the contract. Putting its domain inside `interfaces/telegram_bot` would break the
thin-adapter rule (ADR-005).

## Decision

1. **New top-level layer `apps/`.** An app owns a domain and its storage and is used by
   interfaces. Enforced by `tools/check_layers.py`:
   - `apps/*` may import `shared.*`. It must not import `workflows.*`, `interfaces.*`,
     another app, or transport frameworks (`aiogram`, `fastapi`, `starlette`, `uvicorn`).
   - `interfaces/*` may import apps. `shared/*` and `workflows/*` must not.
   - The LLM-SDK ban stays on `interfaces/*` only, so an app may call a provider itself,
     as a workflow may.
2. **`apps/notes`** (package `notes`) holds the domain, sqlite store, Enrichment
   (providers, SSRF guard, pipeline, sweeper) and the Classifier port. The pipeline reports
   through a `notify(item)` callback instead of calling Telegram. Its glossary, ADRs 0001–0006,
   spec and tickets moved along under `apps/notes/`.
3. **Interfaces.** `interfaces/telegram_bot` gains an admin-only 💾 path
   (`documents.admin_input_handler`, `handlers/notes.py`, `notes_ui.py`). `interfaces/notes_web` is the sorting UI, a
   separate `notes-web` service on `127.0.0.1:8082`, reached over SSH like the dashboard.
4. **Routing: ask first for the admin** (revised 2026-09-29 after trying save-first in
   Telegram). Every non-command text or link from the admin is answered at once with
   `[💾 В заметки] [✖️ Cancel]`. The same message then becomes the usual price card with 💾
   on top. Plain text is priced as a `.txt` document. If fetching or pricing fails, the card
   keeps 💾, so an unscrapable link (Instagram, TikTok) can still be saved. 💾 turns the card
   into the Item's Acknowledgement. Notes ADR-0006 (save first, enrich second) still holds
   once 💾 is tapped. A saved link's 🤖 button reopens the card. Documents never offer 💾.
   Invitees see no change. A card that was cancelled or saved while it was still being
   priced is no longer overwritten when pricing finishes, which also fixes an old Cancel
   race for everyone. Narrowed by notes ADR-0009: only a single website link gets the card;
   💾 deletes it and the Acknowledgement is a reaction.
5. **Storage.** A separate sqlite file (`NOTES_DB_PATH`, `/data/notes.sqlite3` in
   production) on the existing `appdata` volume. Notes and the bot's usage tables share
   nothing.
6. **No automated tests** (ADR-001 unchanged). maxi-notes' pytest suite was left behind.
   The smoke surface is `uv run notes-smoke <url-or-text>`: fetch and file one input and
   print the result.
7. **Classifier provider is OpenAI** (notes ticket 05, `NOTES_CLASSIFIER_PROVIDER=openai`),
   so every paid call in the repo still goes to one provider and one key. It costs about
   $0.002 an Item and is logged, not gated: only the admin saves, and the admin is exempt
   from the daily cap. `fake` stays for offline runs.

## Consequences

+ One bot, one deploy, one set of hardening and docs.
+ One card answers "what do I do with this?" for anything the admin sends. Nothing is
  saved without the admin choosing it.
- A new layer to learn. The checker enforces it, and `docs/architecture.md` describes it.
- Enrichment's outbound fetches run in the bot container (SSRF-guarded, same caps).
- maxi-notes' git history stays in that repo; this repo starts Notes at the merge commit.
- The maxi-notes droplet deploy (ticket 02) was on a droplet that no longer exists, so
  there was no data to migrate.
