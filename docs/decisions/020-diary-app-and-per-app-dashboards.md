# ADR-020: A diary app, and a Dashboard inside each Mini App tab

Status: Accepted (2026-10-08). Amends ADR-016 (decision 1: what the Mini App holds) and ADR-015 (a second app).

## Context

The owner wants a diary of what got done, modelled on Хулендарь (hoolendar.ru): short Entries per Day,
a Mark on the Day (💀 😐 🔥), and Summaries where the best Entries are raised from a Week into its
Month and Year. Until now the Mini App's tabs were «Дашборд» and «Заметки», and the Dashboard
described only notes. A second app makes «the Dashboard» ambiguous. Vocabulary: `apps/diary/CONTEXT.md`.

## Decision

1. **A separate app, `apps/diary`**, with its own database file `diary.sqlite3`, reached only
   from the Mini App. An Entry has no Status, Due, Enrichment or Source, so it is not a notes Item.
   Chat routing is unchanged: every text to the bot is still a notes Capture.
2. **A Summary is a Level on the Entry, not a copy.** An Entry has one Level (day, week, month,
   year). Raise («+») and lower («−») move it one step, at any time. A Summary is the Entries at or
   above its Level inside its window. Editing or deleting an Entry changes every Summary it sits in.
3. **An Entry's own Day decides its window.** A week that spans two months splits between them,
   so an Entry from 30 September can reach only September's Summary.
4. **Tabs are apps; each tab has a `[Дашборд | …]` toggle.** The top row is «Заметки», «Дневник»
   and ⚙️. Each tab opens on its Dashboard. A launch opens «Заметки»; `✏️ Открыть` still opens the
   Item directly.
5. **The diary's Dashboard** is a year heatmap coloured by Mark (drawn as two half-year maps, so a Day
   stays big enough to tap on a phone), then counts (Entries, Days with
   an Entry, the current Streak, 🔥 Days), the most repeated Entry and the best Month (most 🔥
   Days, then most Entries).

## Considered and rejected

- **Diary Entries as notes Items** in a Section: half of the Item's fields and rules would not apply.
- **Copying an Entry into a Summary**, which would let it be reworded: two texts that drift
  apart, and a chain of copies from Week up to Year.
- **A Week belongs to the Month of its Thursday (ISO).** Then a September Entry shows in
  October's Summary, and in December and January in the wrong Year's.
- **Re-tapping the open tab to switch views**: nothing on screen shows that it can be done.
- **Hoolendar's seven Entries per Day**: they would block filling in a missed Day. An Entry is
  capped at 120 characters instead.

## Consequences

- `diary.sqlite3` joins the daily Backup (`infrastructure/backup.py` `DATABASES`, ADR-018) and
  `droplet.sh sql`.
- The diary's views follow ADR-019: a snapshot on the phone, one round of parallel calls.
- Left out for now: the week's mood, search, export, a quote of the day, a Sunday reminder in
  the chat, and adding Entries from the chat (`/day` can come later without touching routing).
