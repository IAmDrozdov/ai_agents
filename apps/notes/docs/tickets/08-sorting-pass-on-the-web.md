# 08 — Sorting pass in the Mini App

**What to build:** The Mini App's Заметки tab becomes the sorting surface (ai_agents ADR-016; the SSH-tunnel web UI this ticket was written for is gone). Filters by Sections (several at once), Status, Placement and unreviewed; pages of 50; an item view, opened from a card or from the `✏️ Открыть` button on a saved-item message (`/?item=<id>`), to set Sections, Status, Placement and Reviewed, edit the Annotation, re-enrich, and hard-delete a trashed Item; bulk actions to archive everything done, mark the current list reviewed, and empty the Trash. Every `/api` call needs Telegram-signed data from the admin. The UI is Russian.

**Blocked by:** 11 — Mini App walking skeleton

**Status:** done (deployed 2026-09-29; checked with signed requests, in a browser, and by real taps in Telegram Web)

- [x] The unreviewed filter lists only unreviewed Items and stops listing an Item after any edit on it
- [x] Filtering by two Sections lists Items in either; filtering by Placement trashed lists only trashed Items; the default view lists only active Items with done ones last
- [x] Setting an Item's Sections with none ticked leaves it in Other, and the app says so
- [x] Archive-all-done moves every done active Item to archived and touches nothing else; mark-reviewed marks exactly the Items in the current filter
- [x] Hard delete answers 409 for a non-trashed Item and removes a trashed one; empty-trash removes every trashed Item
- [x] Re-enrich flips a failed Item back to pending and clears its error
- [x] Editing the Annotation persists and shows on the next request; every string from the database is inserted as text, never as HTML
- [x] Every `/api` call without valid initData answers 401, and one for another user id answers 403
- [x] A page holds 50 Items, and «Показать ещё» appends the next page without mixing filters
- [x] `/?item=<id>` opens that Item's view, and the `✏️ Открыть` button on a saved-item message carries it
