# 09 — Section management on the web

**What to build:** A Sections page where the Owner creates, renames, recolours, re-emojis, reorders, re-hints and deletes Sections. Other cannot be deleted. Deleting a Section drops it from its Items and re-homes any Item left without Sections to Other. New Sections immediately appear in the bot keyboard and in what the Classifier is told on the next Capture.

**Blocked by:** 08 — Sorting pass on the web

**Status:** ready-for-agent

- [ ] Creating `Подарки` with an emoji, colour and hint yields the slug `podarki` and it appears on the Sections page and as a filter chip (seam 7)
- [ ] Renaming, changing colour/emoji/hint and reordering persist and show on the next request (seam 7)
- [ ] Deleting a Section that was an Item's only Section leaves that Item in Other; an Item with other Sections just loses the deleted one (seams 7 and 1)
- [ ] Deleting Other is refused with 400 and Other still exists afterwards (seams 7 and 1)
- [ ] The Classifier request for the next Capture includes the new slug and hint (seam 5)
- [ ] The Acknowledgement keyboard for a new Capture has a Подарки toggle (seam 6)
- [ ] A duplicate slug or an empty name is rejected with a clear message and nothing is created (seam 7)
