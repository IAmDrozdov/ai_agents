# diary

The admin's diary of what got done, modelled on Хулендарь (hoolendar.ru): short Entries per Day, a
Mark on the Day (💀 😐 🔥), and Summaries where the best Entries are raised from a Week into its Month
and Year. Reached only from the admin Mini App's «Дневник» tab; nothing in the chat writes to it (ADR-020).

- Vocabulary: `CONTEXT.md` (Day, Entry, Mark, Level, Raise, Week/Month/Year, Streak, Dashboard, Summary)
- Decision: `docs/decisions/020-diary-app-and-per-app-dashboards.md`

## Layout

| Where | What |
|---|---|
| `apps/diary/src/diary/` | `domain.py` (every diary rule: Entries, Marks, Levels, Summaries, the Dashboard, the Streak, suggestions), sqlite store (`db.py`) |
| `interfaces/telegram_bot/…/miniapp/api_diary.py` | the signed JSON API under `/api/diary`; turns the page's `tz` into «today» |
| `interfaces/telegram_bot/…/miniapp/static/diary.js`, `diaryboard.js` | «Записи» (the Week, the Day editor, Month and Year) and the diary Dashboard |

## Rules worth knowing

- A Day is a local calendar date (`YYYY-MM-DD`), stored as text; the app has no Zone and takes
  «today» from its caller.
- A Summary is a Level on the Entry, not a copy: a window's Summary is its Entries at or above its
  Level. An Entry's own Day decides its window, so a Week across two Months splits between them.
- Month candidates are the Month's week-Level Entries; Year candidates are the Year's month-Level ones.
- The Streak counts Days with an Entry back from today, or from yesterday while today is empty; a
  Mark alone does not count.

## Run

```bash
uv run telegram-miniapp                            # http://127.0.0.1:8083, opened from Telegram
uv run python tools/miniapp_local.py up            # throwaway DBs with 🧪 diary data and a signed URL
```

The schema is created on first start. The Mini App only accepts Telegram-signed requests, so check
it as in `docs/verifying.md` §2.

| Variable | Default | Meaning |
|---|---|---|
| `DIARY_DB_PATH` | `data/diary.sqlite3` | sqlite location (compose pins `/data/diary.sqlite3` for `miniapp` only) |

Production: `infrastructure/droplet.sh sql diary '<SELECT …>'` reads it; the daily Backup copies it
(ADR-018).
