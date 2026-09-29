# maxi-notes v1 — Telegram capture bot + sorting web UI

Status: ready-for-agent

> **Merged into ai_agents (2026-09-29, ADR-015).** This spec was written for the standalone
> `maxi-notes` repo. Where it disagrees with the merge, the merge wins:
> - **Bot:** no own bot. The Owner is the ai_agents admin (`ADMIN_TELEGRAM_ID`). Capture is
>   **ask first**: anything sent gets a card with 💾 В заметки, the priced agents, and Cancel. 💾
>   turns the card into the Acknowledgement. There is no automatic Capture of every message.
>   Invitees never see notes. A saved link's Acknowledgement carries a 🤖 button back to the agents.
> - **Classifier:** OpenAI, not Claude (ticket 05). `CLASSIFIER_*` settings are `NOTES_CLASSIFIER_*`.
> - **Testing:** no automated tests (ai_agents ADR-001). "Testing Decisions" and every "(seam N)"
>   tag below are historical; checks are manual or through `uv run notes-smoke`.
> - **Deployment:** services `bot` (shared) and `miniapp` in the ai_agents compose stack, sqlite at
>   `/data/notes.sqlite3` on its `appdata` volume. There is no `maxi-notes` compose project.
> - **Web UI:** replaced by the admin Mini App (ai_agents ADR-016), served by the `miniapp` service.
>   Story 27 (SSH tunnel, no login page) and the "Telegram Mini App or any public HTTPS ingress;
>   authentication on the web UI" out-of-scope line no longer apply: the app is public over HTTPS and
>   every API call needs Telegram-signed data from the admin. Wherever this spec says "the web", read
>   "the Mini App".

## Problem Statement

While scrolling Instagram, reels, YouTube and the rest, the Owner keeps seeing things worth coming
back to — a video, an article, a restaurant, a product, a place, a library for a pet project. Today
every one of them gets forwarded to Telegram Saved Messages, which turns into an unsorted pile
that can only be scrolled. Nothing in the pile says what a thing was, why it was saved, or whether
it has already been dealt with, so the pile is rarely revisited and slowly loses its value.

## Solution

A private Telegram bot the Owner throws links and text at from the phone. Every message is saved
instantly and acknowledged. Links are enriched in the background — title, Source, author, caption,
thumbnail — and every Item gets a Russian Gist and an automatic Filing into one or more Sections
(Посмотреть, Почитать, Поесть, Купить, Сходить, Работа, Пет-проекты, Остальное, plus the Owner's
own). Each Item carries a Status (new / started / done) and a Placement (active / archived /
trashed). From the bot the Owner can Browse a Section and tick things off; on a private web UI
reached over an SSH tunnel the Owner runs the periodic sorting pass: filters, corrections, bulk
tidying, Section management, trash. The app is fully useful even if the sorting pass never happens.

## User Stories

1. As the Owner, I want to share a link to the bot from my phone in one action, so that the thing I just saw is captured before I lose it.
2. As the Owner, I want to send a plain text message (an idea, a place, a thing to buy) and have it saved the same way, so that capture doesn't depend on having a link.
3. As the Owner, I want an instant Acknowledgement for every Capture, so that I know it is saved even if Enrichment later fails.
4. As the Owner, I want the bot to fetch the title, author and caption of a Link, so that I don't have to remember why I saved it.
5. As the Owner, I want a short Russian Gist for every Item, so that I can scan a list without opening anything.
6. As the Owner, I want the bot to file every Item into Sections automatically, so that I never face an unsorted pile.
7. As the Owner, I want to fix a Filing with one tap on the Acknowledgement, so that a wrong guess costs me a second, not a session.
8. As the Owner, I want a Link I already saved not to be saved twice, and to be told where it already is, so that the store stays clean.
9. As the Owner, I want a Link I trashed earlier to come back when I send it again, so that resending is the natural "undo".
10. As the Owner, I want to be told when a resent Link is in the Archive and be able to bring it back with one tap, so that archived things stay archived unless I say otherwise.
11. As the Owner, I want to Browse a Section from inside the bot when I'm out (a bookshop, a cinema, a restaurant), so that my lists are with me.
12. As the Owner, I want to mark an Item started, done or archived from the bot with one tap, so that ticking things off actually happens.
13. As the Owner, I want to see all Items on the web with filters by Section, Status and Placement, so that I can find what I'm looking for.
14. As the Owner, I want a filter for Items I haven't reviewed yet, so that the sorting pass has a concrete list.
15. As the Owner, I want to edit an Item's Sections, Status, Placement and Annotation inline on the web, so that the sorting pass is fast.
16. As the Owner, I want to archive everything done in one click, so that finished things leave my sight without ceremony.
17. As the Owner, I want to mark everything in the current view as reviewed in one click, so that a glance can close a sorting pass.
18. As the Owner, I want to trash Items and restore them, and have the Trash empty itself after 30 days, so that deletion is safe but not permanent housekeeping.
19. As the Owner, I want to empty the Trash or delete a trashed Item now, so that I can get rid of things immediately when I choose.
20. As the Owner, I want to create my own Sections with a name, emoji, colour and a hint, so that the bot files into them correctly.
21. As the Owner, I want to rename, recolour, reorder and delete Sections, so that the set fits my life as it changes.
22. As the Owner, I want the Other Section to always exist, so that nothing is ever unfiled.
23. As the Owner, I want the bot and the web UI in Russian, and the Gist always in Russian whatever the source language, so that I read it the way I think.
24. As the Owner, I want failed Enrichment to retry by itself and to be able to retry it manually, so that a flaky site doesn't leave an Item bare forever.
25. As the Owner, I want a Link from a private Instagram account to still be saved with my Annotation, so that "couldn't read it" never means "lost it".
26. As the Owner, I want the bot to answer only me, so that nobody else can read or fill my store.
27. As the Owner, I want the web UI reachable only through my SSH tunnel with no login page, so that there is no auth surface to defend.
28. As the Owner, I want to deploy with one script to the droplet I already run, so that hosting costs nothing extra.
29. As the Owner, I want to switch the LLM provider or model by changing configuration, so that I'm not locked in.
30. As the Owner, I want several links in one message to become separate Items each carrying my words, so that one share of a thread doesn't collapse into one Item.
31. As the Owner, I want a photo, voice message or document to get a clear "text and links only" reply, so that I know it wasn't saved.
32. As the Owner, I want an Item that was interrupted mid-Enrichment by a restart to finish on its own, so that operations never need my attention.

## Implementation Decisions

### Domain model

- An **Item** is either a **Link** (a URL plus an optional **Annotation** — the Owner's words in the same message) or a **Note** (plain text). Its attributes: title, Source, author, caption (fetched; Classifier input, shown collapsed), Gist, thumbnail URL, Status, Placement, Reviewed, Enrichment state, the Telegram chat and message ids of its Acknowledgement, timestamps.
- **Sections** are tags: an Item is in one or more (ADR-0002). A Section has a stable slug, a Russian name, an emoji, a colour, a one-line hint for the Classifier, a position, and a built-in flag. **Other** (slug `other`) is seeded, undeletable, and receives any Item that would otherwise have none — the invariant "every Item has at least one Section" is enforced in the domain layer, including when the last Section is removed from an Item and when a Section is deleted.
- Starter Sections seeded on first run: Посмотреть 🍿 (`watch`), Почитать 📖 (`read`), Поесть 🍜 (`eat`), Купить 🛒 (`buy`), Сходить 📍 (`go`), Работа 💼 (`work`), Пет-проекты 🛠 (`pet`), Остальное 📦 (`other`), each with a hint and a distinct colour.
- **Status** (`new` / `started` / `done`) and **Placement** (`active` / `archived` / `trashed`) are independent axes (ADR-0003). No automatic archiving in v1; Trash purges after 30 days (configurable); Archive never purges.
- **Filing is optimistic** (ADR-0001): the Item lands in the Classifier's Sections immediately with `reviewed = false`. Reviewed flips on any web edit, an explicit ✓, or a Section change from the bot keyboard.
- **Dedupe** is by normalised URL: scheme and host lower-cased, leading `www.`/`m.` dropped, fragment dropped, tracking parameters dropped (`utm_*`, `fbclid`, `gclid`, `igsh`, `igshid`, `si`, `feature`, `ref`, `ref_src`), remaining query sorted, trailing slash stripped; `youtu.be/<id>` and YouTube Shorts normalise to `youtube.com/watch?v=<id>`; Instagram post/reel/tv paths normalise to the bare shortcode path. A repeat produces no new Item; a trashed match is restored to active; an archived match stays archived and the reply offers a return button.
- URL extraction prefers Telegram message entities (`url`, `text_link`) and falls back to a conservative regex; the Annotation is the message text with URLs removed. Several URLs in one message become several Items, each carrying the Annotation. Non-text messages are not Items.

### Storage

sqlite in WAL mode, one file on a shared volume, read and written by both processes with a connection per call. Shape (a decision, recorded once):

- `sections(id, slug UNIQUE, name, emoji, color, hint, is_builtin, position, created_at)`
- `items(id, kind ∈ {link,note}, url, url_normalized UNIQUE where not null, text, title, source, author, caption, gist, image_url, status ∈ {new,started,done}, placement ∈ {active,archived,trashed}, reviewed, enrichment_status ∈ {pending,done,failed,skipped}, enrichment_attempts, enrichment_error, next_enrich_at, tg_chat_id, tg_ack_message_id, created_at, updated_at, trashed_at)`
- `item_sections(item_id, section_id)` with cascading deletes; foreign keys on.

### Enrichment (ADR-0006, ADR-0005)

- Save first: the Item and its Acknowledgement exist before any fetch or Classifier call. Enrichment runs as a background task in the bot process and is also driven by a sweeper (every 60 s) that picks due work from the database: scheduled retries, and `pending` Items with no schedule older than two minutes (lost in-flight work after a restart). The sweeper is the only retry mechanism; a manual re-enrich from the web merely flips the Item back to `pending`.
- Providers by host: YouTube via its oEmbed endpoint (title, author, thumbnail) plus best-effort description from the watch page; Instagram via Meta's tokenless `instagram_oembed` (author, thumbnail, caption extracted from the embed HTML); TikTok via its oEmbed (title, author, thumbnail); everything else via a generic page fetch with metadata extraction (title, author, description, image, site name). Every outbound fetch passes an SSRF guard (http/https only, no userinfo, host must resolve to a public address, redirects vetted hop by hop). Provider failure is not pipeline failure: the Classifier still runs on whatever was fetched (possibly only the Annotation and domain).
- Backoff on retryable failure: 1 min, 5 min, 30 min, 2 h, 12 h; after five attempts the Item is `failed` and the web shows the error with a re-enrich action. Notes skip fetching and go straight to the Classifier (`skipped` fetch state, then `done`).
- Outbound HTTP for oEmbed goes through a small HTTP port with an aiohttp implementation (10 s timeout, identifying user agent), so tests can substitute fixture payloads.

### Classifier (swappable)

- A `Classifier` port: `file(request) -> Filing`. The request carries kind, URL, Source, title, author, caption (truncated to 2000 characters), Annotation, and the **current list of all Sections with slugs and hints**. The Filing carries `sections` (slugs, validated against the request; empty → `["other"]`), `gist` (Russian, one or two sentences, no emoji), and cleaned `title` / `author` / `source`.
- Provider and model are configuration: `CLASSIFIER_PROVIDER` (`claude` | `fake`), `CLASSIFIER_MODEL` (default `claude-opus-5`), `CLASSIFIER_EFFORT` (default `low`). The Claude adapter uses the official SDK's structured-output parse call with a stable, cached system prompt; the volatile Section list travels in the user turn. A refusal or an authentication/bad-request error files the Item to Other with the error recorded and no retry; rate limits, server errors and connection errors go to backoff. Server-side refusal fallbacks are not enabled. A deterministic fake Classifier exists for tests and offline runs. Adding another provider is one adapter module plus a configuration value.

### Bot (aiogram, long polling)

- Only the configured Owner id is answered; every other update is dropped and logged. Private chats only.
- Commands: `/start` (help), `/help`, `/list` (Browse). Every other text/caption message is a Capture — no intent detection.
- Acknowledgement text while pending: "💾 Сохранено · 📦 Остальное / ⏳ Разбираю ссылку…" (Notes: "⏳ Разбираю…"); after Enrichment: the Section line (emoji + name, joined by " · "), the title in bold, the Gist, and "Source · author" in italics. All remote and Owner strings are HTML-escaped.
- Keyboard on every Acknowledgement and item card: one toggle button per Section (✅ prefix when on), then Начато / Готово / В архив, and Вернуть for archived Items. Toggling off the last Section adds Other and shows a toast saying so. Any tap sets Reviewed. Callback data stays within Telegram's 64-byte limit.
- Dedupe reply reuses the keyboard: "🔁 Уже сохранено: …" with Sections and Status; "♻️ Достал из корзины: …" when restored; "📦 Лежит в архиве: …" with Вернуть when archived.
- Browse: `/list` shows Sections with active counts; a Section shows pages of five active Items (new/started first, then done; newest first) with numbered buttons opening an item card and ◀️ ▶️ paging; archived and trashed Items never appear.
- Non-text messages get "Пока понимаю только текст и ссылки."

### Web UI (FastAPI, server-rendered, htmx partials, no build step)

- Loopback only, host header restricted to localhost, no auth (ADR-0004).
- List with filters: Sections (multi), Status, Placement (default active), unreviewed; 50 per page; done Items sink to the bottom, newest first otherwise. Header chips show Sections with counts.
- Each row: thumbnail, title as an outbound link, Source · author, Gist, editable Annotation, collapsed caption, coloured Section chips, Status control, Placement actions, Reviewed check, Enrichment badge with error and re-enrich action when failed. Every inline action re-renders only that row. Hard delete is allowed only for trashed Items.
- Bulk actions: archive all done, mark current view reviewed, empty trash.
- Sections page: create / rename / emoji / colour / hint / position / delete with confirmation; Other cannot be deleted (server refuses); deleting re-homes orphaned Items to Other.

### Deployment

- Own repository, own Docker Compose project (`maxi-notes`) on the ai_agents droplet: one image, services `bot` (memory cap 300 MB) and `web` (160 MB, published on 127.0.0.1:8082), one named volume for sqlite. Hardened like ai_agents: non-root, read-only image, dropped capabilities, tmpfs `/tmp`, pid limits, bounded logs.
- Deploy script: rsync the repo to `/opt/maxi-notes/src`, upload an allow-listed env file (bot token, Owner id, LLM key, classifier settings, housekeeping knobs, log level; the web service gets no secrets), build on the droplet, start, and wait for the health endpoint and the bot's "polling as @" log line. Droplet IP from an argument or from the ai_agents Terraform output. Terraform and the firewall are never touched from this repo.
- Configuration via environment / `.env`: bot token, Owner id, LLM key, classifier provider/model/effort, database path, web host/port, trash TTL days, sweep interval, log level.

## Testing Decisions

- Full TDD: for every acceptance criterion the failing test is written first at its seam, then the minimal code to pass it; one criterion per cycle; refactoring happens in the per-ticket review, not inside the loop.
- A good test verifies behaviour through a public interface and survives refactors; expected values are independent literals from this spec; nothing verifies by reading the database behind the interface.
- Seams under test (pre-agreed): (1) the domain API over a real temporary sqlite file; (2) URL normalisation and extraction as pure functions; (3) each Enrichment provider over saved fixture payloads through the HTTP port; (4) the Enrichment pipeline with fake HTTP, fake Classifier and a recording Telegram session; (5) the Classifier request rendering and the Claude adapter's mapping over a stubbed SDK client; (6) the bot through the real dispatcher fed synthetic updates, observed through a recording Telegram session; (7) the web through the ASGI test client, verified by follow-up requests.
- Fakes only at system boundaries: the Telegram API session, the LLM SDK client, outbound HTTP, and the clock (domain functions that compare times accept `now`). The database is never faked. No test touches the network or needs a real API key.
- Prior art: none in this repository; the sibling ai_agents repo has no tests by its own decision, so the patterns come from the tdd skill rather than from existing code.

## Out of Scope

- Telegram Mini App or any public HTTPS ingress; authentication on the web UI.
- Multiple users or invites.
- Text search.
- Image or video analysis; downloading thumbnails (only the URL is stored).
- Instagram private content via cookies or any automation of the Owner's account (forbidden by ADR-0005).
- An OpenAI adapter (the port exists; the adapter does not).
- Automatic archiving rules; per-Section Status vocabularies.
- Editing Terraform or the firewall in ai_agents.
- Live-LLM or live-network tests.

## Further Notes

- Droplet memory: 1 GB RAM + 2 GB swap shared with ai_agents (its bot is capped at 700 MB). If the two caps here don't fit, the knob is a bigger droplet, not lifting caps.
- oEmbed rate limits (1,000/h on the token route; possibly lower tokenless) are irrelevant at single-owner volume.
- The Owner may switch the default model to a cheaper one at any time by configuration; the default follows the current API reference.
