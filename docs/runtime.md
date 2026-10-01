# Runtime: what runs, what each part does, how they talk

`docs/architecture.md` is the import layering. This file covers the running system: processes,
data and message flow, and the state that lives only in memory. Read it before touching the bot,
the notes path or the deploy. Shorthand: `telegram_bot/x.py` and `handlers/x.py` mean
`interfaces/telegram_bot/src/telegram_bot/…`; `deploy.sh` means `infrastructure/deploy.sh`.

## Processes (one image, `infrastructure/docker/docker-compose.yml`)

| Service | Entry point | Does | Reads / writes |
|---|---|---|---|
| `bot` | `telegram-bot` (`telegram_bot/__main__.py`) | Telegram long polling. Answers users, prices cards, runs one job at a time (`worker.worker_loop`), and runs notes enrichment plus the notes sweeper | `telegram_bot.sqlite3` rw, `notes.sqlite3` rw, OpenAI, YouTube, the web |
| `miniapp` | `telegram-miniapp` (`telegram_bot/miniapp`) | The admin Mini App: a public static shell plus a signed JSON API for notes and usage, `127.0.0.1:8083` (ADR-016) | `telegram_bot.sqlite3` read, `notes.sqlite3` rw |
| `funnel` (profile) | `tailscale/tailscale` | Publishes `miniapp` over HTTPS through Tailscale Funnel, outbound only (ADR-016) | `tsstate` volume |
| `warp` (profile) | wireproxy | SOCKS5 egress for yt-dlp only (ADR-014) | — |
| — | `smoke`, `notes-smoke` | Terminal-only reference runs (ADR-001) | local files |

The services share only the `appdata` volume (`/data/*.sqlite3`, WAL mode, a connection per
call). The bot reaches `warp` through `YTDLP_PROXY=socks5h://warp:40000`, and `funnel` reaches
`miniapp` at `http://miniapp:8083`. The droplet accepts no inbound connections: Telegram is polled
outbound, the Mini App is published by the funnel sidecar's outbound tunnel, and SSH is opened
for the operator's address only while `infrastructure/ssh-gate.sh` runs a command (ADR-017).

## The three agents (workflows, ADR-012)

| id | Accepts | Delivers | Paid calls |
|---|---|---|---|
| `doc_translator` | Document | Translated Markdown, one chapter at a time | chat |
| `pdf_tts` | Document | Voice message(s), optionally translated first | chat + TTS |
| `yt_dub` | Link (YouTube only) | Dubbed voice-over; captions first, STT fallback | chat + TTS (+ STT) |

A non-YouTube link is scraped into a Markdown `DocumentSource` (`telegram_bot/scrape.py`) and
then offered to the document agents. Admin plain text becomes `message.txt`. Every agent is
`preview` (free) → `estimate` (free) → `run` (paid).

## Who gets what (routing)

Updates pass through `AccessMiddleware` first: private chats only, admin or whitelisted users
only, plus `/start <invite>`. Routers then match in the order set in
`handlers/__init__.py:setup_routers`, and the first match wins:

| Router | Message it takes | Who |
|---|---|---|
| `start` | `/start`, `/help` (the admin's help adds a notes line) | everyone |
| `admin` | `/invite`, `/users`, `/revoke` | admin |
| `notes` | callbacks (`JobCB save`, `NotesCB`); messages: an Instagram / YouTube / TikTok link (`direct_link_handler`), a photo, video or non-agent document (`file_handler`), and a voice or round video message (`voice_handler`, a Voice, transcribed in Enrichment) are saved with no card (notes ADR-0007, ADR-0008) | admin |
| `documents` | an agent document (.pdf .docx .md .markdown .txt) → card; **admin** text or caption → card with 💾 (`admin_input_handler`); anyone else's text containing a URL → card (`link_handler`) | all |
| `settings_menu`, `status` | `/settings`, `/status`, `/cancel` | all |

Plain text without a URL from an invitee matches nothing and is ignored.

Callback-data prefixes (`keyboards.py`, `notes_ui.py`, max 64 bytes): `m` menu, `o` option
picker, `s` set value, `t` try voice/model, `j` job actions (`run`/`settings`/`cancel`/`save`),
`n` notes item actions (`offer`/`restore`). Pick a new letter for a new family.

## The card lifecycle (`handlers/documents.py`)

1. **Open.** An answer is sent at once: a status line, with `[💾 В заметки] [✖️ Cancel]` for the
   admin. That message becomes the card; `_live[chat]` points at it.
2. **Intake.** Scrape, parse, preview and estimate run on a 2-thread `_INTAKE_EXECUTOR`, one per
   user, with a 120 s timeout.
3. **Card.** The status line is edited into the card: 💾 (admin), one priced button per agent,
   then ⚙️ Settings and ✖️ Cancel. The job sits in `pending[chat]`, **one per chat**.
4. **Outcome:**
   - **Run** puts a `Job` on the FIFO `JobQueue` (max 5 per user, one running at a time). The
     worker edits the card with progress and delivers files or voice messages.
   - **Cancel** closes the card.
   - **💾** closes the card and turns it into the notes Acknowledgement.
   - **Settings → Back** re-prices the same card.

Guards: only the card's own `pending` item can be run, cancelled or reopened. A card closed
while it was still pricing is never overwritten. A card superseded by a newer message is edited
to "⏭ Replaced…" and keeps 💾.

Spend gates (`_spend_block_reason`): a per-job cap (`BOT_MAX_JOB_COST_USD`) applies to everyone,
including the admin. The rolling 24 h cap (`BOT_DAILY_USER_COST_LIMIT_USD`) applies to everyone
except the admin.

## Notes path (`apps/notes`, ADR-015)

💾 → `notes.save_handler` → `documents.take_draft` → `_save` (`capture_link` per URL with
dedupe, or `capture_note`) → the card becomes the Acknowledgement → `enrich_later` →
`notes.enrich.pipeline.enrich_item`:

1. The provider fetch runs through the SSRF guard: YouTube and TikTok oEmbed, the Instagram
   captioned embed page, or a generic page. A Voice is downloaded from Telegram instead (the bot
   passes `telegram_download` in, max 20 MB) and transcribed by `shared.audio.transcribe`; the
   Transcript is stored at once, so a Classifier retry does not pay for STT again.
2. The Classifier (`NOTES_CLASSIFIER_PROVIDER`: `openai`, or `fake` offline) chooses the
   Sections, the Russian Gist and the title.
3. `store_enrichment` saves the result, and `notify` edits the Acknowledgement.

Failures go to `schedule_retry` (backoff 1 min → 12 h, then `failed`). The sweeper
(`NOTES_ENRICH_SWEEP_SECONDS`) retries anything due and anything a restart interrupted. On a
saved link, 🤖 runs `documents.offer_link` again. `apps/*` never imports aiogram: the bot
passes `notify` and `download` in as callbacks. If notes fails to start, the bot runs without it and 💾
answers "Notes are unavailable".

Language: the bot UI is English; notes texts and the Mini App are Russian.

## Admin Mini App (`telegram_bot/miniapp`, ADR-016)

While `BOT_MINIAPP_URL` is set, the bot gives the admin's chat a `📒` menu button
(`__main__.set_admin_menu_button`, at startup, for that chat only), and every saved-item message
a `✏️ Открыть` button (`notes_ui.item_keyboard`, a `web_app` button with `/?item=<id>`). Both open
the `miniapp` service through the funnel sidecar: a static shell (`miniapp/static`, vanilla JS)
that calls `/api/usage` and `/api/notes/*`. The Заметки tab filters, pages, edits an item
(Sections, Status, Placement, Annotation, Reviewed), re-enriches, deletes a trashed one, and runs
the bulk actions. "💬 Показать в чате" sets `show_requested_at` and closes the app; the bot's show
loop (`NotesRuntime.start_show_loop`, every 2 s) replies to the Item's original message, or sends
the file again by `file_id` if that message is gone (notes ADR-0008). The Секции tab creates, edits, reorders and deletes Sections. Enrichment never
overwrites the Sections of an Item the Owner has already reviewed.

Every `/api` call carries `Authorization: tma <initData>`. `miniapp/auth.py` checks Telegram's
HMAC against `MINIAPP_INIT_SECRET`, requires `auth_date` under 24 h and admits only
`ADMIN_TELEGRAM_ID` (401 or 403). The API only parses and serialises; the rules stay in
`apps/notes`. A re-enrich from the app flips the Item to `pending` and the bot's sweeper does
the work. Edits made in the app do not re-render Acknowledgement messages in the chat.

## State that lives only in memory

These are lost on every restart, and a deploy is a restart:
- `pending` cards: TTL 30 min, 60 MB cap.
- `drafts` and `_live`/`_closed`.
- The job queue.

After a restart, old buttons answer "expired", and a job left running is marked `interrupted`
at startup (`db.reconcile_running_jobs`). Notes enrichment survives, because the sweeper picks
up anything left `pending` from sqlite.

## Touch points when you change…

- **An env var:**
  - `shared/src/shared/config.py` (`Settings`, a singleton read at import: a value that fails
    validation kills *every* process, so prefer plain `str`/`int` fields);
  - `.env.example`;
  - the allow-list regex in `infrastructure/deploy.sh` (only `OPENAI_API_KEY`,
    `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `LOG_LEVEL`, `YTDLP_PROXY`, `BOT_*` and `NOTES_*`
    reach the droplet as `bot.env`). Two files go up separately: `miniapp.env`
    (`ADMIN_TELEGRAM_ID`, `LOG_LEVEL` and the derived `MINIAPP_INIT_SECRET`) and `funnel.env`
    (`TS_AUTHKEY`). A variable the Mini App needs goes into the first;
  - the README tables.
  Compose `environment:` overrides `bot.env`.
- **A service or workspace package:**
  - the manifests stage in `infrastructure/docker/Dockerfile` (one `COPY <pkg>/pyproject.toml`
    per member);
  - a service in compose;
  - the health wait in `deploy.sh`.
  Workspace packages are installed editable, so templates and static files are served from
  `/app/<path>` rather than site-packages.
- **A router or filter:** the order in `setup_routers`. Keep `start` first, and keep each
  router's `allowed_user_filter`.
- **A new agent:** `.skills/create-workflow.md`. It appears on cards through
  `telegram_bot/registry.py`; there are no id switches.

## Production facts

- **Droplet:** 1 vCPU, 961 MB RAM plus 2 GB swap. Memory caps are bot 700 MB, miniapp 160 MB,
  funnel 96 MB and warp 64 MB; together they exceed RAM, so keep new services small.
- **YouTube:** metadata and audio from the droplet IP need `warp`. oEmbed, the Instagram embed
  page and TikTok oEmbed work directly.
- **Telegram:** at most one poller per token. Running `telegram-bot` locally while production
  is up causes 409 Conflict. Occasional `Bad Gateway` lines in the log are Telegram-side noise.
