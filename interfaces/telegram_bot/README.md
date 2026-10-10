# interfaces/telegram_bot

Private Telegram bot exposing every workflow in `registry.py` (`doc_translator`,
`pdf_tts`, `yt_dub`) through the job contract (ADR-005 thin adapter, ADR-012), plus the admin
Mini App for notes, the diary and usage (`miniapp/`, ADR-016, ADR-021). Both use the bot's sqlite database
(`TELEGRAM_DB_PATH`); the Mini App also writes the notes database.

Responsibilities:
- parse Telegram updates, download documents (≤20 MB Bot API cap)
- accept a pasted link and scrape its main article to Markdown (trafilatura,
  `scrape.py`), then feed it into the same priced-action flow as an uploaded `.md`
- turn an upload, a YouTube link or an article link into a `Source`, preview and
  price it for every workflow that accepts that kind, and show cost + ETA on one-tap
  action buttons (no separate confirm step); settings still reachable from the card
- history-backed ETA (`eta.py`): median sec/char from the jobs table, LRU cache
  rebuilt every few finished jobs, cold-start priors until enough samples exist
- inline-keyboard selection of languages, models, voice (persisted per user)
- call `WORKFLOW.run` in a worker thread; one job at a time (FIFO queue)
- deliver `FileDeliverable`s as documents and `AudioDeliverable`s as **voice messages** (see below)
- access control: single admin (`ADMIN_TELEGRAM_ID`) mints one-time invite links
  (`/invite` → `t.me/<bot>?start=<token>`); redeemed users are whitelisted in sqlite
  until the admin runs `/revoke <id>`; private chats only
- record every job (chars, cost USD + cost lines, facts, duration, status) for the Mini App's «Расходы» screen

Non-responsibilities: no prompt/template logic, no direct LLM SDK usage.

## Failure messages

A failed job answers one question first: **wait, or go fix something?** The worker
passes the exception to `shared.failures.diagnose()`, which classifies it and — for
provider-side verdicts only — *verifies* the claim with a live unbilled probe
(`models.list()`) plus OpenAI's status page, so "OpenAI is down" is measured rather
than assumed. The probe also catches the opposite case: if their API answers again,
the message says the error was a passing blip and the job is worth retrying now.

| Scope | Shown as | Meaning |
|---|---|---|
| `provider` | 🟡 Their side (OpenAI) | 5xx, 429, timeout, connection failure — clears itself |
| `config` | 🔴 Our side — configuration | bad key, missing quota, wrong model id |
| `internal` | 🔴 Our side — bug | anything unrecognised; check the logs |
| `input` | 🟠 This document | 400/422, or a workflow-reported error |

The usage log stores the scope too (`[provider] OpenAI server error: HTTP 500…`), so
the «Расходы» screen can tell an outage apart from a real regression after the fact.

## Audio delivery

Audio results are sent with `sendVoice`, not `sendAudio` — only a voice message
gets a waveform and the 1×/1.5×/2× playback-speed control, which is the point when
the result is an hour of narration. Consequences:

- **The audio format is not user-selectable.** Telegram renders voice messages only
  from Ogg/Opus, so `SpeechSpec.output_format` defaults to `opus` and `/settings`
  has no format row.
- **Duration is always passed explicitly.** Telegram derives length from container
  metadata only for short clips; past ~5 minutes a voice message shows `0:00` with a
  dead scrub bar unless `duration=` is supplied. It comes from
  `shared.audio.concat_ogg_opus()`. If the duration is unknown the worker sends an audio
  file instead of a voice note with a broken scrub bar.
- **Fallback.** Telegram Premium users can refuse inbound voice messages
  (`VOICE_MESSAGES_FORBIDDEN`); the worker retries as an audio file.
- **Known cosmetic issue.** Voice messages longer than ~10–15 minutes render a flat
  waveform until the recipient downloads them
  ([telegram-bot-api#354](https://github.com/tdlib/telegram-bot-api/issues/354)).
  Playback, seeking and speed control are unaffected.

## Adding a workflow

One `RegistryEntry` in `registry.py` (label, short label, hint keys, settings → config
builder in `user_config.py`). Nothing else in the bot changes.

## Run

```bash
uv run telegram-bot                                   # long polling, no ingress
uv run telegram-miniapp --host 127.0.0.1 --port 8083  # Mini App server (Funnel publishes it in prod)
```

Env (via `shared.config.Settings` / `.env`): `TELEGRAM_BOT_TOKEN`,
`ADMIN_TELEGRAM_ID`, `TELEGRAM_DB_PATH`, `OPENAI_API_KEY`, `BOT_MINIAPP_URL`, plus the operator policy
`BOT_LANGUAGES`, `BOT_DEFAULT_SOURCE_LANGUAGE`, `BOT_DEFAULT_TARGET_LANGUAGE`,
`BOT_MAX_JOB_COST_USD`, `BOT_DAILY_USER_COST_LIMIT_USD` (defaults in `shared/config.py`;
a user's own `/settings` choices override the language defaults).

## Cost guards

`BOT_MAX_JOB_COST_USD` refuses any single job estimated above it. `BOT_DAILY_USER_COST_LIMIT_USD`
refuses a non-admin user's job once their rolling 24h spend (finished + queued + running,
re-priced at Run) would exceed it; the admin is exempt. The window is fixed in `catalog.py`.

## Bot commands

- `/start [invite-token]` — redeem an invite / show help
- `/help`, `/settings`, `/status`, `/cancel`
- `/invite`, `/users`, `/revoke <telegram_id>` — admin only

## Notes (admin only)

The admin's text and links get the usual card with 💾 В заметки on top; 💾 saves them as notes
Items (`apps/notes`, ADR-015). The routing table, card lifecycle and notes path are in
`docs/runtime.md`.

## Mini App (admin only, ADR-016)

The admin's chat has a `📒` menu button while `BOT_MINIAPP_URL` is set. It opens the `miniapp` service
(`miniapp/`): a static shell plus a JSON API.

Routes: the "Admin Mini App" section of `docs/runtime.md`.

Every `/api` call needs `Authorization: tma <initData>` (Telegram-signed, at most 24 h old, admin
id only: 401 or 403 otherwise). The routes only parse and serialise; notes rules live in
`apps/notes`. Setup and checks: `infrastructure/README.md`, `docs/verifying.md`.

Phone UI rules (found on an iPhone, 2026-09-29; the shell in `miniapp/static`):

- Form controls are at least 16 px, and the viewport has `maximum-scale=1`. Below that iOS zooms
  the page on focus and never zooms back, so every screen is clipped at the right edge.
- Nothing is `sticky` or `fixed` at the top: Telegram's native header covers the top edge of the
  webview, so a sticky row of tabs slid half under it (the title row that replaced it scrolls with the
  page). Menus and the toast are popups over the page, not bars. `disableVerticalSwipes` keeps a scroll at
  the top from dragging the whole sheet.
- A tap rebuilds only what it changed. Controls are built once and only flip a class or text;
  lists are reconciled by id (`core.reconcile`), so kept rows keep their images; a new view is
  swapped in after its data arrives, never a blank; a reset keeps the old list until the new
  one is here; no whole-view dimming; an edit shows at once and the server's answer confirms it.
