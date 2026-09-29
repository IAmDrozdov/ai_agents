# 07 — Browse from the bot

**What to build:** `/list` shows the Sections with their active-Item counts; choosing one shows pages of five active Items — new and started first, then done, newest first within each — with numbered buttons that open an item card carrying the full Filing keyboard, and paging buttons. Archived and trashed Items never appear.

**Blocked by:** 06 — Filing keyboard on the Acknowledgement

**Status:** ready-for-agent

- [ ] `/list` produces one message listing the eight starter Sections with their emoji, names and active counts (seams 6 and 1)
- [ ] Opening a Section with seven active Items shows five with a ▶️ button; page two shows the remaining two with a ◀️ button (seam 6)
- [ ] Done Items are listed after new and started ones; within a group newest first (seam 6)
- [ ] Archived and trashed Items are never listed and are not counted (seams 6 and 1)
- [ ] Tapping a numbered button sends an item card whose text and keyboard equal the Acknowledgement rendering for that Item (seam 6)
- [ ] A Section button back to the Sections menu exists on every page (seam 6)
- [ ] The bot's command list (shown by Telegram) contains `start`, `help` and `list` with Russian descriptions (seam 6)
