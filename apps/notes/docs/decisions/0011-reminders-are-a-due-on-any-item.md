# A Reminder is a Due on any Item, not a fifth kind; the bot writes for Reminders only

The Owner wants the bot to hand things back at a set moment and to move that moment later. Any
Item can be a Reminder: a Link, Note, File or Voice that has a Due. Its kind does not change, so a
Link keeps its Source, preview and URL dedupe, and removing the Due makes it a plain Item again.
Overdue (Due passed, Status todo) is read off the clock and is not a Status value, because Status is
the Owner's decision and stays `todo` / `done` (ADR-0010).

The Classifier finds the Due during Enrichment in any text the Item has: a Note, an Annotation, a
Voice's Transcript. "напомни" is a strong hint in the prompt, not a separate route, because a spoken
"напомни" exists only once the Transcript does. It fills an empty Due and never changes or clears
one. The Owner sets, moves (to any future moment) or removes a Due in the Mini App.

A misread Due fails silently until the moment is missed, so the bot breaks ADR-0009's rule for
Reminders alone: one line naming the Due when a Capture becomes a Reminder, and one reply to the
original Capture message when the Due arrives. The reply is sent once; after that an ignored
Reminder lives on as Overdue in the Mini App.

## Considered Options

- A fifth kind, `reminder` — rejected: a Link given a Due would lose its Link fields, and taking the Due off has nothing to go back to.
- Overdue as a third Status value — rejected: the clock would change a value only the Owner sets.
- A deterministic "напомни …" route at Capture beside the Classifier — rejected: a Voice has no text at Capture, and Russian phrasings like «в пятницу вечером» parse better with the Classifier.
- Reaction only, the Due checked in the Mini App — rejected: a wrong Due is only found when the Reminder does not come.
- Repeating the reminder until answered, or a daily digest — rejected: Overdue keeps it visible; a digest can come later on top.
- Recurring Reminders — rejected for now: "done" would stop meaning done (ADR-0010).

## Consequences

- Amends ADR-0009: the bot leaves a message for a Reminder (the Due line and the reminder itself), nothing else.
- Amends ADR-0010: a re-sent Link whose text asks to be reminded gets the Due and goes back to `todo`; a re-send without one still changes nothing.
- A done Item is never reminded and never Overdue; its Due is kept, so taking it back to `todo` before the Due restores the reminder.
- "Через N" counts from Capture. A Due already passed when Enrichment ends (backoff) sends the reminder at once.
- Due is stored in UTC and read in the Owner's zone, which notes remembers from the Mini App's `tz`; UTC until the Mini App first opens.
- The sweeper sends due Reminders, so one arrives up to one sweep late, and a Due missed while the bot was down goes out on the first sweep after start.
