# interfaces/telegram_bot

Private Telegram bot exposing every workflow in `registry.py` (`doc_translator`,
`pdf_tts`, `yt_dub`) through the job contract (ADR-005 thin adapter, ADR-012), plus a
localhost-only usage dashboard. Both share one sqlite database (`TELEGRAM_DB_PATH`).

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
- record every job (chars, cost USD + cost lines, facts, duration, status) for the dashboard

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
the dashboard can tell an outage apart from a real regression after the fact.

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
uv run telegram-bot                                  # long polling, no ingress
uv run usage-dashboard --host 127.0.0.1 --port 8081  # dashboard (SSH tunnel in prod)
```

Env (via `shared.config.Settings` / `.env`): `TELEGRAM_BOT_TOKEN`,
`ADMIN_TELEGRAM_ID`, `TELEGRAM_DB_PATH`, `OPENAI_API_KEY`, plus the operator policy
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

`handlers/notes.py` sits before `documents`: the admin's non-command text and links become notes
Items (`apps/notes`, ADR-015), acknowledged in Russian (`notes_ui.py`) and enriched in the
background. The 🤖 button on a link runs `documents.offer_link`, the same flow a pasted link
takes for everyone else. The notes sweeper starts next to the worker in `__main__.py`.

## Dashboard

- `GET /` — totals, by-user and by-user×agent aggregates, call history
- `GET /api/usage` — same as JSON
- `GET /healthz`

No auth by design: bind 127.0.0.1 and access via `ssh -N -L 8081:127.0.0.1:8081 root@<droplet>`.
