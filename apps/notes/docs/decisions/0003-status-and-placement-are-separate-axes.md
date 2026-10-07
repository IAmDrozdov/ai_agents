# Status and Placement are separate axes

_Superseded by ADR-0010 (2026-10-07): Placement is gone and Status is `todo` / `done`. The rest of this record is history._

Status (`new` / `started` / `done`) is progress toward the thing the Item is for; Placement
(`active` / `archived` / `trashed`) is visibility. Archiving is an explicit act by the Owner and
nothing is archived automatically in v1 except through an explicit bulk action, so a reference
Item can be archived without ever being done, and a done Item can stay visible until the Owner
tidies.

## Considered Options

- Status as the whole lifecycle (`new → started → done | dropped`), with "Archive" just the view of done + dropped — rejected: a kept-but-not-actionable Item has no honest home.
- No Status at all, only active / archived / trashed (Pocket / Raindrop style) — rejected: the Owner asked for "started", which a half-watched series needs.

## Consequences

- Default views show `active` Items with `done` sunk to the bottom; Archive and Trash are opt-in views.
- Trash purges after 30 days; Archive never purges.
- Multi-section Items (ADR-0002) make Status necessarily an attribute of the Item, not of a Section membership.
