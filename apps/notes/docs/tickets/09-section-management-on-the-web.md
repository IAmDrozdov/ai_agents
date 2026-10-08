# 09 — Section management in the Mini App

**What to build:** A «Секции» tab where the Owner creates, renames, recolours, re-emojis, reorders, re-hints and deletes Sections (maxi-bot ADR-016; the SSH web UI this ticket was written for is gone). Other cannot be deleted. Deleting a Section drops it from its Items and re-homes any Item left without Sections to Other. A new Section shows up at once in the filter chips and in the item view, and in what the Classifier is told on the next Capture.

**Blocked by:** 08 — Sorting pass in the Mini App, 11 — Mini App walking skeleton

**Status:** done (deployed 2026-09-29; checked with signed requests, in a browser, and by real taps in Telegram Web)

- [x] Creating «Подарки» with an emoji, colour and hint yields the slug `podarki`, and it appears in the Секции tab and as a filter chip
- [x] Renaming, changing colour, emoji and hint, and reordering persist and show on the next request; the slug never changes
- [x] Deleting a Section that was an Item's only Section leaves that Item in Other; an Item with other Sections just loses the deleted one
- [x] Deleting Other is refused with 400 and Other still exists afterwards
- [x] The Classifier request for the next Capture includes the new slug and hint
- [x] The item view has a toggle for the new Section
- [x] A duplicate name or an empty name is rejected with a clear message and nothing is created
- [x] Every Section route without valid initData answers 401, and one for another user id answers 403
