# Runtime: what runs, what each part does, how they talk

`docs/architecture.md` is the import layering. This file covers the running system: processes,
data and message flow, and the state that lives only in memory. Read it before touching the bot,
the notes path or the deploy. Shorthand: `telegram_bot/x.py` and `handlers/x.py` mean
`interfaces/telegram_bot/src/telegram_bot/…`; `deploy.sh` means `infrastructure/deploy.sh`.

## Processes (one image, `infrastructure/docker/docker-compose.yml`)

| Service | Entry point | Does | Reads / writes |
|---|---|---|---|
| `bot` | `telegram-bot` (`telegram_bot/__main__.py`) | Telegram long polling. Answers users, prices cards, runs one job at a time (`worker.worker_loop`), and runs notes enrichment plus the notes sweeper, show loop, reminder loop and, once per start, the Thumbnail backfill | `telegram_bot.sqlite3` rw, `notes.sqlite3` rw, OpenAI, YouTube, the web |
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
then offered to the document agents. Plain text reaches them only as a `.txt` file. Every agent is
`preview` (free) → `estimate` (free) → `run` (paid).

## Who gets what (routing)

Updates pass through `AccessMiddleware` first: private chats only, admin or whitelisted users
only, plus `/start <invite>`. Routers then match in the order set in
`handlers/__init__.py:setup_routers`, and the first match wins:

| Router | Message it takes | Who |
|---|---|---|
| `start` | `/start`, `/help` (the admin's help adds a notes line) | everyone |
| `admin` | `/invite`, `/users`, `/revoke` | admin |
| `notes` | callbacks (`JobCB save`, `NotesCB offer` / `restore` / `done`: a Reminder's ✅ Готово marks the Item done and edits the message to «✅ сделано»); messages saved with no card and acknowledged by a reaction (notes ADR-0007, ADR-0008, ADR-0009): text with no URL, several URLs, or exactly one Instagram / YouTube / TikTok URL (`direct_text_handler`, one Note or Link); a photo, video or non-agent document (`file_handler`); a voice or round video message (`voice_handler`, a Voice, transcribed in Enrichment) | admin |
| `documents` | an agent document (.pdf .docx .md .markdown .txt) → card; **admin** text with exactly one website URL → card with 💾 (`admin_input_handler`); anyone else's text containing a URL → card (`link_handler`) | all |
| `settings_menu`, `status` | `/settings`, `/status`, `/cancel` | all |

Plain text without a URL from an invitee matches nothing and is ignored.

Callback-data prefixes (`keyboards.py`, `notes_ui.py`, max 64 bytes): `m` menu, `o` option
picker, `s` set value, `t` try voice/model, `j` job actions (`run`/`settings`/`cancel`/`save`),
`n` notes item actions (`offer`/`restore`/`done`). Pick a new letter for a new family.

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
   - **💾** saves one Item, deletes the card and reacts on the admin's original message.
   - **Settings → Back** re-prices the same card.

Guards: only the card's own `pending` item can be run, cancelled or reopened. A card closed
while it was still pricing is never overwritten. A card superseded by a newer message is edited
to "⏭ Replaced…" and keeps 💾.

Spend gates (`_spend_block_reason`): a per-job cap (`BOT_MAX_JOB_COST_USD`) applies to everyone,
including the admin. The rolling 24 h cap (`BOT_DAILY_USER_COST_LIMIT_USD`) applies to everyone
except the admin.

## Notes path (`apps/notes`, ADR-015)

Text (`direct_text_handler`) and 💾 on a card (`save_handler` → `documents.take_draft`) go
through `_capture_draft`: one Item per Capture, `capture_link` with dedupe for exactly one URL,
else `capture_note` with the whole text. Files and voice (`file_handler`, `voice_handler`) go
through `capture_file` / `capture_voice`. Then `enrich_later` → `notes.enrich.pipeline.enrich_item`. The bot sends no message of its own (a Reminder is the exception): the Acknowledgement
is its one reaction on the admin's message (`notes_ui.react`): ✍ working, 👌 in notes, 👎 take a
look (notes ADR-0009). A duplicate gets 👌 at once with no Enrichment (👎 if its Enrichment had
failed), and keeps its Status, `done` included, unless its own words ask for a reminder (below). A
Capture that throws, or notes being down, gets 👎. The bot writes a message for Reminders only
(notes ADR-0011, below). Enrichment:

1. The provider fetch runs through the SSRF guard: YouTube and TikTok oEmbed, the Instagram
   captioned embed page, or a generic page. A Voice is downloaded from Telegram instead (the bot
   passes `telegram_download` in, max 20 MB) and transcribed by `shared.audio.transcribe`; the
   Transcript is stored at once, so a Classifier retry does not pay for STT again.
2. The Classifier (`NOTES_CLASSIFIER_PROVIDER`: `openai`, or `fake` offline) chooses the
   Sections, the Russian Gist and the title, and reads a Due when the text asks to be reminded.
   It is told the Capture moment in the Owner's zone; the fake reads «напомни YYYY-MM-DD HH:MM».
3. `store_enrichment` saves the result (a Due fills an empty Due only, and one not after the
   Capture moment is dropped), and `notify` (`NotesRuntime.notify_for`) sets the reaction from
   `enrichment_status` on `tg_message_id`; when Enrichment filled a Due that is still ahead it also
   replies to the Capture with «⏰ пт, 10 окт, 19:00» and a web_app `📅 Перенести`.

Failures go to `schedule_retry` (backoff 1 min → 12 h, then `failed`). The sweeper
(`NOTES_ENRICH_SWEEP_SECONDS`) retries anything due and anything a restart interrupted; a retry
leaves ✍ in place. `apps/*` never imports aiogram: the bot passes `notify` and `download` in as
callbacks. If notes fails to start, the bot runs without it: direct messages get 👎, a link still
gets its card, and 💾 answers "Notes are unavailable". The `NotesCB` `offer` and `restore`
handlers stay only for buttons on old Acknowledgement messages: 🤖 still works, ↩️ only removes
itself (notes ADR-0010); `done` is current (Reminders, below).

**Reminders (notes ADR-0011).** An Item with a Due (`due_at`, UTC) is a Reminder.
`NotesRuntime.start_reminder_loop` runs `remind_once` every 30 s: `claim_due_reminders` marks
`reminded_at` and returns the todo Items whose Due has come in one `UPDATE … RETURNING`, so each goes
out once, and the bot replies to the Item's Capture message with `✅ Готово` (`NotesCB done`) and
`📅 Перенести` (a web_app to `/?item=<id>`); if the original is gone it sends a message naming the Item
instead, and a network error hands the claim back for the next pass. Moving or removing a Due clears
`reminded_at`; back to `todo` after the Due sets it, so nothing fires late. A re-sent Link whose words
ask for a reminder goes through `Classifier.due`, and the saved Item gets the Due and reopens. The
Owner's zone is the Mini App's last `tz` (a `settings` row, UTC until the app first opens). Overdue
(todo, Due passed) is read off the clock and never stored.

Language: the bot UI is English; notes texts and the Mini App are Russian.

## Admin Mini App (`telegram_bot/miniapp`, ADR-016)

While `BOT_MINIAPP_URL` is set, the bot gives the admin's chat a `📒` menu button
(`__main__.set_admin_menu_button`, at startup, for that chat only). It opens
the `miniapp` service through the funnel sidecar: a static shell (`miniapp/static`, vanilla JS)
that calls `/api/usage` and `/api/notes/*`. It has two tabs and a ⚙️ button; each tab is mounted
once per launch and keeps its state in memory until the app closes.

Funnel costs 250–450 ms a request, so the app is built to need few requests (ADR-019):
- **Shell and assets.** The shell `/` is revalidated on every launch (ETag = a hash of the shell). Assets live
  under `/static/<build>/` and are cached for good. All modules load in one round trip
  (`modulepreload`).
- **Compression.** Responses over 500 B are gzipped.
- **Snapshot.** The last answers are kept on the phone (`DeviceStorage`, else `localStorage`: Telegram Web answers DeviceStorage `UNSUPPORTED`;
  `core.js` snapshots). The Dashboard, the Sections and the open lists paint from them at once,
  then refresh behind them.

- **Дашборд** (first) is infographics only (`GET /api/notes/dashboard?tz=<IANA zone>`): the todo
  count with «просрочено: N» beside it when anything is Overdue, two 26-week heatmaps of Items
  Captured and done per day (days in the Owner's time zone, from `created_at` and `done_at`), and a
  bar per Section with todo Items (`todo_count` from `/api/notes/sections`). A bar is tappable: it
  opens Заметки with that Section expanded on «Сделать»; so is «просрочено: N», which opens the
  «Просрочено» row. The request's `tz` is also stored as the Owner's zone.
- **Заметки** starts with a «⏰ Просрочено» row when something is Overdue
  (`/api/notes/items?overdue=true`, every Section, todo only, earliest Due first; collapsed on
  launch, no switch, hidden in Search and edit mode). It lists every Section in the Owner's order as a
  collapsed accordion. A header shows the
  count for that Section's own «Сделать» | «Готово» switch (`todo_count` / `done_count`, one Status
  per view, notes ADR-0010); an expanded Section pages `/api/notes/items?section=…&status=…`, newest
  first, and an Item under several Sections shows in each. Search (`/api/notes/items?q=`, 300 ms
  after typing stops, at most 100 results) covers both Statuses and every text field but the URL,
  folded by the `fold()` SQL function the notes `Database` registers on each connection (casefold,
  «ё» as «е»). «Изменить» shows headers only: drag ⋮⋮ to reorder (`PUT /api/notes/sections/order`),
  ✏️ for the Section form, «+ Новая секция» at the end.
- **⚙️** opens Расходы (`/api/usage`) over the tabs; Telegram's back button returns.

The item view (`detail.js`) edits an item (Sections, Annotation, «✓ Готово» / «↩ Вернуть», which
also sets or clears `done_at`, and the Due: «+ Напомнить» reveals a date-time input, «×» removes it,
a past moment is a 422), re-enriches, and deletes it at once behind a confirm; it reports each
change back, and the accordion refreshes its counts and open lists, all in parallel. While an item
on screen is still being enriched, the app asks about that item alone (`/api/notes/items?ids=`). The
gap grows 3 s → 30 s, or lasts until its scheduled retry. Once it settles, the lists refresh.
The app also reloads the shown tab when it becomes visible again; there is no push. A card's
picture is the Item's Thumbnail (`/api/notes/items/{id}/thumb?v=<etag>`, notes ADR-0012), never a
third-party URL. "💬 Показать в чате" sets `show_requested_at` and closes the app; the bot's
show loop (`NotesRuntime.start_show_loop`, every 2 s) replies to the Item's original message, or sends
the file again by `file_id` if that message is gone (notes ADR-0008). Enrichment files an Item only
while it is in Other alone; once it is anywhere else, re-enrich keeps its Sections.

Every `/api` call carries `Authorization: tma <initData>`. `miniapp/auth.py` checks Telegram's
HMAC against `MINIAPP_INIT_SECRET`, requires `auth_date` under 24 h and admits only
`ADMIN_TELEGRAM_ID` (401 or 403). The API only parses and serialises; the rules stay in
`apps/notes`. A re-enrich from the app flips the Item to `pending` and the bot's sweeper does
the work. Edits made in the app do not change the reaction in the chat.

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
- **Funnel:** the Mini App's name resolves to three ingress IPs, picked at random per connection,
  and they differ a lot. Measured 2026-10-07 (TLS handshake, 5 samples each): `185.40.234.55` 0.11 s,
  `.198` 0.45–0.77 s, `.75` 3.9–5.3 s. A slow launch can be the ingress, not the app (ADR-019).
  Compare with `curl --resolve <host>:443:<ip> -w '%{time_appconnect}'`.
- **YouTube:** metadata and audio from the droplet IP need `warp`. oEmbed, the Instagram embed
  page and TikTok oEmbed work directly.
- **Telegram:** at most one poller per token. Running `telegram-bot` locally while production
  is up causes 409 Conflict. Occasional `Bad Gateway` lines in the log are Telegram-side noise.
- **Data:** the databases live only in the `appdata` volume, and the File and Voice bytes only in
  Telegram. The Owner's Mac pulls a daily Backup of both into iCloud Drive (ADR-018;
  `infrastructure/README.md` "Backups", with the restore procedure).
