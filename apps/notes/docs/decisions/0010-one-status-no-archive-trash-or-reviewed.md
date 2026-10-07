# One Status, todo or done; no Archive, Trash or Reviewed

An Item carries one state the Owner sets: Status, `todo` or `done`, and `done` means the Owner
has taken the Item up (a series they started watching is done), not that they finished it.
Placement (active / archived / trashed) and Reviewed are gone, with every operation on them:
three axes and a sorting pass were more mechanics than one person's save-for-later store needs.
Status stays, with the moment it turned `done` (`done_at`), because it feeds later infographics.
The Mini App lists one Status at a time, `todo` by default, and deletes an Item at once behind a
confirm.

## Considered Options

- Drop Status too — rejected: what got done, and when, is what the infographics will count.
- Keep `started` (ADR-0003) — rejected: the Owner does not track work in progress; starting a thing is taking it up.
- Show `done` Items in the `todo` list, sunk to the bottom — rejected by the Owner: one Status per view.
- Keep the Trash as a safety net — rejected: a confirm is enough, and a deleted Link can be sent again.
- An undo toast instead of the confirm — rejected: it brings back a hidden pending-delete state.
- A hidden "filed by the Owner" flag in place of Reviewed — rejected: the Filing rule below needs no column.
- A log of every Status change — rejected: one `done_at` answers "done when".

## Consequences

- The Classifier files an Item only while it is in Other alone. Once the Item is in any other Section, Enrichment (re-enrich included) refreshes the Gist, title and the rest and leaves the Sections. This replaces ADR-0001's Reviewed guard; Filing stays optimistic, with no inbox.
- A re-sent Link that is `done` stays `done` and gets 👌; this replaces ADR-0009's "an archived or trashed duplicate goes back to active".
- Migration: `new` and `started` become `todo`, archived Items become `done`, trashed Items are deleted for good, and migrated Items have no `done_at`. Back up `notes.sqlite3` before the deploy.
- Section counts count `todo` Items. Ticket 10's Trash purge (never built) is dropped.
