# ADR-018: Daily Backup pulled to the Owner's Mac

Status: Accepted (2026-10-07).

## Context

Everything the bot keeps had one copy: the `appdata` volume on the only droplet. DigitalOcean
backups were off and there were no snapshots, so a dead droplet, a `terraform destroy` or a bad
migration would lose the notes (every Item, Section, Filing and Status), the invitee list and the
usage history for good. The bytes of Files and Voices are not on the droplet at all: notes keep a
`file_id`, which works only with the current bot token. The docs' two copy recipes were wrong
too: a `cat` of a WAL database, and a root-run online backup on the host, which can create
root-owned `-wal`/`-shm` files that lock the bot's `app` user out.

## Decision

1. **Scope.** A **Backup** holds consistent copies of both sqlite databases and the bytes of every
   File and Voice. It does not hold the Tailscale and WARP identity volumes (recoverable), the
   in-memory cards and queue (by design), logs or `.env`.
2. **The Mac pulls.** `infrastructure/backup.py` runs on the Owner's Mac. It opens the SSH gate
   (ADR-017) for its own address and feeds `infrastructure/backup_snapshot.py` to
   `docker compose run --rm --no-deps -T bot python -`: a one-off container of the bot image with
   the same volume. The snapshot program runs as the container's `app` user, never as root on the
   host, takes an online backup of each database into memory, and returns a tar on stdout. It works
   while the bot is down. Nothing new runs on the droplet: no service, secret or outside account.
3. **Verified before it lands.** Each copy is checked on the Mac (sha256, `PRAGMA integrity_check`,
   row counts) in a local staging dir. The day folder then moves into the Backup dir with a single
   rename, so iCloud never syncs a half-written database.
4. **Bytes from the Bot API.** The Mac downloads each File and Voice it does not have yet with
   `getFile`, using the bot token from `.env`. `getFile` does not conflict with the bot's polling.
   Files over Telegram's 20 MB download limit are listed as `too_big`, not fetched. A file is named
   by Item id plus a hash of its `file_id`, because restoring an older Backup hands out old ids again.
5. **Location.** iCloud Drive `Backups/maxi-bot/`: one folder per local date, plus one shared
   `files/` folder (`MAXI_BOT_BACKUP_DIR` overrides the location). There is no encryption in the
   script. Apple's Advanced Data Protection covers iCloud Drive, and a Backup stays a plain sqlite
   file that opens without a key.
6. **Retention.** The newest 30 day folders. A file stays while a kept manifest lists its Item, so
   a deleted Item or a revoked invitee leaves the Mac within about 30 days.
7. **Schedule.** A LaunchAgent runs the command hourly and at login, and a run exits at once when
   today's Backup exists. Sleep therefore only delays a Backup. `--force` takes one now and keeps
   today's earlier one aside.
8. **Alerts.** A macOS banner plus a message from the bot to `ADMIN_TELEGRAM_ID`. They come for a
   failed run (from the second failure in a row, or at once when the last good Backup is over 48
   hours old) and for a file that could not be fetched (other than `too_big`). The same reason
   alerts at most once per 24 hours.
9. **Restore is a documented manual procedure** (`infrastructure/README.md` "Backups"), rehearsed
   once. Bytes are never put back into the bot.

## Rejected alternatives

- **The droplet pushes to S3, R2 or Spaces:** it needs a new secret and an outside account on the
  droplet, against the closed-by-default stance of ADR-017.
- **The bot stores bytes at Capture:** no extra safety, since they die with the droplet. It also
  uses the 25 GB disk and touches the freshly settled Capture path.
- **The bot sends a dump to Telegram:** 50 MB limit, the same provider, and it cannot carry the
  bytes.
- **DigitalOcean droplet backups:** whole-droplet, crash-consistent only, and paid monthly.
- **Encryption in the script:** a key is easy to lose on the day of a restore.

## Consequences

+ Losing the droplet costs at most a day of notes, and the files survive the loss of the bot token.
+ The copies are taken as `app` inside the container, so a Backup cannot lock the bot out.
- Backups happen only while the Mac is awake, and they depend on its network. Port 22 opens for
  about a minute a day.
- Apple holds the data, end-to-end encrypted only under Advanced Data Protection.
- A schedule that stops running (the agent unloaded, the repo moved) cannot alert about itself; only
  a check outside the Mac could, and none exists.
- A database over 100 MB stops the snapshot: the copy is held in memory (`/tmp` is RAM too) inside
  a 700 MB container. Revisit when the notes grow that far.
