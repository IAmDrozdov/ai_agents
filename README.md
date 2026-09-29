# ai_agents

Turn long documents and YouTube videos into translations and voice-overs from a
private Telegram bot that shows the price before it spends anything.

Three workflows, one job contract, two interfaces:

| Workflow | In | Out |
|---|---|---|
| `doc_translator` | PDF / DOCX / Markdown / text, or a pasted article link | chapter-by-chapter translation as Markdown |
| `pdf_tts` | same | narrated audio (Telegram voice message), optionally translated first |
| `yt_dub` | YouTube link | voice-over of the video in your language (captions first, speech-to-text fallback) |

- **Telegram bot** (`interfaces/telegram_bot`): send a file or link, get a card with
  every applicable workflow priced and ETA'd, tap one to run. Languages, models and
  voice are per user. Invite-only. Usage dashboard on localhost.
- **Smoke runner** (`interfaces/smoke`): the same contract from the terminal —
  preview, price, confirm, run, write the result.

All paid calls go to OpenAI (chat, TTS, STT). Every run is estimated first and gated
by a per-job cap and a per-user daily cap.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- An OpenAI API key — <https://platform.openai.com/api-keys>
- For the bot: a Telegram account

## Quick start (terminal)

```bash
git clone <this repo> ai_agents && cd ai_agents
uv sync --all-packages
cp .env.example .env            # fill OPENAI_API_KEY at minimum
uv run smoke doc_translator README.md
```

The runner prints a free preview and a price, asks before spending, and writes the
result to `dist/smoke/`. Any workflow knob can be overridden with `--config`:

```bash
uv run smoke pdf_tts book.pdf --config '{"translation": {"target_language": "German"}}'
uv run smoke yt_dub https://www.youtube.com/watch?v=...
```

## Run the bot

1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, put the token into
   `TELEGRAM_BOT_TOKEN`.
2. Message [@userinfobot](https://t.me/userinfobot) to get your numeric id, put it into
   `ADMIN_TELEGRAM_ID`. That account is the admin: it mints invites and is exempt from
   the daily cap.
3. `uv run telegram-bot`, open your bot in Telegram, press Start.
4. `/invite` gives a one-time link for each person you let in; `/users` and
   `/revoke <id>` manage them.

Commands: `/settings` (languages, models, voice — remembered per user), `/status`,
`/cancel`, `/help`. Details: `interfaces/telegram_bot/README.md`.

## Configuration

Everything an operator changes lives in `.env` (`.env.example` is the commented
reference). Workflow behaviour knobs (chunk sizes, backstops, prompts) stay in code under
`workflows/<name>/src/<name>/config.py` on purpose (ADR-004).

| Variable | Default | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | — | required |
| `TELEGRAM_BOT_TOKEN` | — | required for the bot |
| `ADMIN_TELEGRAM_ID` | — | the admin user's numeric id |
| `BOT_LANGUAGES` | English, Russian, Chinese, Japanese, Korean, French, German, Spanish | languages offered in `/settings` |
| `BOT_DEFAULT_SOURCE_LANGUAGE` / `BOT_DEFAULT_TARGET_LANGUAGE` | English / Russian | defaults for a new user |
| `BOT_MAX_JOB_COST_USD` | 10 | refuse a single job estimated above this |
| `BOT_DAILY_USER_COST_LIMIT_USD` | 25 | per-user rolling 24h cap (admin exempt) |
| `YTDLP_PROXY` | — | optional proxy for YouTube requests, e.g. the bundled WARP sidecar (ADR-014) |
| `WARP_ACCEPT_TOS` | — | `yes` starts the WARP sidecar on deploy; you accept Cloudflare's terms |
| `TELEGRAM_DB_PATH` | `data/telegram_bot.sqlite3` | sqlite location |
| `LOG_LEVEL` | `INFO` | |
| `OTEL_*` | off | optional tracing, see below |
| `DO_API_KEY` | — | Terraform only, never read by app code |

Models, prices and voices are one catalogue in `shared/src/shared/pricing.py`. Prices
are estimates; check your OpenAI invoice.

## Security model

- The bot answers only invited users, in private chats; the admin can revoke anyone.
- The usage dashboard has **no authentication** by design: bind it to `127.0.0.1` and
  reach it over an SSH tunnel (see `interfaces/telegram_bot/README.md`, "Dashboard").
- In production the containers run read-only and non-root with memory and pid caps,
  and the droplet exposes SSH only (`infrastructure/README.md`).
- Untrusted documents are parsed inside the bot process; the caps above are the
  blast radius.

## Data handling

- Document text, transcripts and pasted-link content are sent to OpenAI to translate,
  transcribe or synthesize. No document text, transcript or audio is stored by the bot.
- The bot's sqlite database keeps, indefinitely: Telegram ids, usernames, first names,
  filenames, per-job cost and error text, and your `/settings` choices. It's visible on
  the usage dashboard.
- `/revoke` deletes a user and their settings, but their past job rows (the list above)
  stay in the usage log.

## Legal note

`yt_dub` reads captions when a video has them. When it has none, it downloads the
audio track for transcription, which is against YouTube's Terms of Service. Running
that fallback is your decision and your risk (ADR-010).

## Deploy (optional)

`infrastructure/` provisions one DigitalOcean droplet with Terraform and deploys the bot
and dashboard with Docker Compose (`./infrastructure/deploy.sh`). See
`infrastructure/README.md`. AI-agent users can run the `/deploy-bot` skill.

## Observability (optional)

OpenTelemetry export is wired and off by default (`OTEL_ENABLED`), but the code does
not create spans of its own yet; `tools/observability/` holds a local ELK + APM stack as
scaffolding. See `docs/observability/tracing-elk.md`.

## Layout

- `shared/` — settings, logging, the job contract, pricing, document intake, translate/speech/STT stages
- `workflows/<name>/` — workflow business logic (graph/nodes) + its job descriptor (`runtime.py`)
- `interfaces/telegram_bot/` — the Telegram bot + usage dashboard
- `interfaces/smoke/` — terminal runner over the same job contract
- `infrastructure/` — Terraform + Docker deployment to a DigitalOcean droplet
- `docs/` — architecture, conventions, ADRs
- `.skills/` — scaffolding instructions for AI agents
- `tools/check_layers.py` — layer enforcement
- `tools/observability/` — local ELK + APM stack

New interfaces plug in as thin adapters under `interfaces/` holding a registry of
workflow descriptors (ADR-005, ADR-012).

## Docs

- [Architecture](docs/architecture.md), [Conventions](docs/conventions.md), [Tooling](docs/tooling.md)
- [Decisions (ADRs)](docs/decisions/) — binding
- [Workflows index](docs/workflows-index.md), [Glossary](CONTEXT.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). AI agents working in this repo start at `AGENTS.md`.

## License

MIT — see [LICENSE](LICENSE).
