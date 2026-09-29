# 01 — Walking skeleton: a Note from Telegram shows up on the web

**What to build:** The thinnest complete path. The Owner sends a plain text message to the bot and gets an Acknowledgement; the Note is saved in Other; opening the web UI lists it with its Section. Strangers get nothing. This ticket also lays down everything every later ticket stands on: the package, configuration, the database with its schema and seeded Sections, linting and type-checking, and the test harness (temporary-database fixture, recording Telegram session, fake HTTP client, fake Classifier).

**Blocked by:** None — can start immediately

**Status:** done (in maxi-notes, before the merge — ADR-015)

- [x] `uv run maxi-bot` starts, logs `polling as @<bot>`, and exits with a clear error if the bot token or Owner id is missing
- [x] A message from a Telegram id other than the Owner produces no outgoing Telegram call and is logged (seam 6)
- [x] The Owner's text message produces exactly one Item of kind Note, filed in Other, and one outgoing message whose text contains `Сохранено` (seams 1 and 6)
- [x] First start seeds the eight starter Sections with their slugs, names, emoji, colours and hints; `other` is present and marked built-in (seam 1)
- [x] `GET /` renders the Note's text and its Section chip; `GET /healthz` returns `{"status":"ok"}` (seam 7)
- [x] `uv run ruff check .`, `uv run ruff format --check .`, `uv run ty check` and `uv run pytest -q` all pass
- [x] Every test runs with no network and no real API key

## Comments

**2026-09-18 — implemented.** Seams exercised: 1 (`tests/test_sections.py`, `tests/test_items.py`), 6 (`tests/test_bot.py` through `Dispatcher.feed_update` and a `RecordingSession`), 7 (`tests/test_web.py` via `TestClient`). Verified by hand: `uv run maxi-bot` without `TELEGRAM_BOT_TOKEN` and then without `ADMIN_TELEGRAM_ID` exits 1 with a one-line error each; `uv run maxi-web --port 8099` boots and serves `/healthz` and `/`. **Not verified here:** the live `polling as @<bot>` line needs a real bot token from @BotFather in `.env` — the Owner runs that once (it is also the deploy gate in ticket 02). Design note: handler modules expose `router()` factories rather than module-level routers, because aiogram attaches a `Router` to exactly one `Dispatcher` and the tests build one per case.

**Review (independent, read-only):** no high-severity findings. Fixed from the report: sqlite connections were committed but never closed (`with conn:` only manages the transaction) → `Database.session()` now commits/rolls back *and* closes; `/list` was advertised in the command list and help before Browse exists → removed until ticket 07; `skipped` was rendered as in-progress → only `pending` shows "⏳"; the read-only URI is now built with `Path.as_uri()` so paths with spaces work. Deferred to ticket 03 by design: a scheme allow-list on `href` (capture will only ever store http/https URLs).
