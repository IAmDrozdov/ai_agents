# Diary glossary

The Owner's diary of what got done, modelled on Хулендарь (hoolendar.ru). Product vocabulary only;
the notes app's terms are in `apps/notes/CONTEXT.md`, and its **Owner** and **Zone** mean the same here.

**Day**:
A calendar date in the Owner's Zone. Entries and a Mark belong to a Day; a past Day can still be written.
_Avoid_: date (in prose), page

**Entry**:
One short line (up to 120 characters) about something the Owner did on a Day; a Day holds any number. It lives in exactly that Day, whatever Summary it is raised to.
_Avoid_: record, note, item, запись дня (in code)

**Mark**:
The Owner's verdict on a whole Day: 💀, 😐 or 🔥. One per Day.
_Avoid_: rating, mood, score, оценка (in code)

**Level**:
How far an Entry has been raised: day, week, month or year. An Entry has one Level; raising moves it one step up.
_Avoid_: rank, tier, priority

**Raise**:
Moving an Entry one Level up (the «+» button), into the Summary of the window that holds its Day; allowed at any time, the window need not be over. Lowering («−») is its undo, one step down.
_Avoid_: promote, pin, star, copy

**Week / Month / Year**:
Windows over Days: Monday to Sunday, a calendar month, a calendar year. An Entry's own Day decides which window it falls in, so a week that spans two months splits between them.
_Avoid_: period, ISO week

**Streak**:
The run of consecutive Days, each with at least one Entry, that ends today or yesterday; today does not break it before it is over. A Mark alone does not count.
_Avoid_: chain, серия (in code)

**Dashboard**:
One of the two Modes of the diary Place (the other is today's Day), infographics only, for one Year: a Day map coloured by Mark, the counts (Entries, Days with an Entry, the Streak, 🔥 Days), the most repeated Entry and the best Month. Tapping a Day opens its Week. Not the notes Dashboard.
_Avoid_: overview, stats, обзор

**Summary**:
The Entries raised to a window's Level: a Week's Summary holds its Entries at week Level or higher, and so on up. Not a separate text: editing or deleting an Entry changes every Summary it sits in.
_Avoid_: digest, recap, highlights, итоги (in code)
