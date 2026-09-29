# ADR-015: An `apps/` layer, and Notes merged in from maxi-notes

Status: Accepted (2026-09-29)

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
3. **Interfaces.** `interfaces/telegram_bot` gains an admin-only notes router
   (`handlers/notes.py`, `notes_ui.py`). `interfaces/notes_web` is the sorting UI, a
   separate `notes-web` service on `127.0.0.1:8082`, reached over SSH like the dashboard.
4. **Routing: save first for the admin.** The notes router is registered before
   `documents`. Every non-command text or link from the admin becomes an Item at once
   (notes ADR-0006). A link's Acknowledgement carries a 🤖 button that runs the unchanged
   link flow (`documents.offer_link`) and shows the usual price card. Documents still go
   straight to the price card. Invitees see no change.
5. **Storage.** A separate sqlite file (`NOTES_DB_PATH`, `/data/notes.sqlite3` in
   production) on the existing `appdata` volume. Notes and the bot's usage tables share
   nothing.
6. **No automated tests** (ADR-001 unchanged). maxi-notes' pytest suite was left behind.
   The smoke surface is `uv run notes-smoke <url-or-text>`: fetch and file one input and
   print the result.
7. **Classifier provider is OpenAI** (notes ticket 05), so every paid call in the repo
   still goes to one provider and one key. Until it lands, `NOTES_CLASSIFIER_PROVIDER=fake`
   files everything to Other with the caption as the Gist.

## Consequences

+ One bot, one deploy, one set of hardening and docs.
+ The admin's pasted links are saved even when they were only meant to be dubbed or
  translated. The price card is one tap further away, and a link sent twice answers with
  the saved Item and the same button.
- A new layer to learn. The checker enforces it, and `docs/architecture.md` describes it.
- Enrichment's outbound fetches run in the bot container (SSRF-guarded, same caps).
- maxi-notes' git history stays in that repo; this repo starts Notes at the merge commit.
- The maxi-notes droplet deploy (ticket 02) was on a droplet that no longer exists, so
  there was no data to migrate.
