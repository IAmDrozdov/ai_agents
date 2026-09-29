# 10 — Housekeeping and restart safety

**What to build:** The system looks after itself: the Trash purges Items older than the configured TTL, the sweeper finishes Enrichment that a restart interrupted, and shutdown lets in-flight work finish cleanly. Nothing in the store ever needs the Owner's attention to stay consistent.

**Blocked by:** 08 — Sorting pass on the web

**Status:** ready-for-agent

- [ ] Purge removes an Item trashed 31 days before `now` and keeps one trashed 29 days before; the TTL is configurable (seam 1)
- [ ] Archived Items are never purged regardless of age (seam 1)
- [ ] One sweeper pass over a pending Item with no schedule and no activity for three minutes enriches it (seams 4 and 1)
- [ ] One sweeper pass runs purge and due Enrichment together and tolerates an empty database (seam 4)
- [ ] Stopping the bot while an Enrichment is in flight does not leave a traceback in the log; on restart the Item completes (seam 4 plus manual)
- [ ] Manual: `docker compose restart bot` mid-Enrichment on the droplet leaves no Item pending for longer than three minutes
- [ ] README documents the housekeeping behaviour and the two knobs (trash TTL, sweep interval)
