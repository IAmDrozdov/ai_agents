# 03 — Links with dedupe

**What to build:** A message containing URLs becomes Link Items — one per URL — each carrying the Owner's remaining words as the Annotation. The same link sent twice is not saved twice: the bot replies with the existing Item and its state; a trashed match is brought back to active and the reply says so; an archived match stays archived and the reply offers a return button. URL normalisation makes `youtu.be`, Shorts, tracking parameters and trailing slashes irrelevant to "the same link".

**Blocked by:** 01 — Walking skeleton

**Status:** done (in maxi-notes, before the merge — ADR-015)

- [x] `https://youtu.be/X?si=abc` and `https://www.youtube.com/watch?v=X&utm_source=share` normalise to the same key; `utm_*`, `igsh`, `fbclid` and fragments are dropped; remaining query parameters are order-independent (seam 2)
- [x] Sending the same link twice leaves one Item; the second reply starts with `🔁 Уже сохранено` and shows its Sections and Status (seams 1 and 6)
- [x] Resending a trashed link restores it to active and the reply starts with `♻️ Достал из корзины` (seams 1 and 6)
- [x] Resending an archived link leaves it archived; the reply starts with `📦 Лежит в архиве` and its keyboard has a `Вернуть` button (seams 1 and 6)
- [x] A message with two links and some words yields two Link Items, each with that Annotation; a message with one link and no words yields a Link with an empty Annotation (seams 2 and 1)
- [x] A URL present only as a `text_link` entity is captured as a Link (seam 2)
- [x] A new Link is filed in Other with Enrichment pending and its Acknowledgement text contains `Разбираю ссылку` (seams 1 and 6)

## Comments

**2026-09-18 — implemented.** Seams: 2 (`tests/test_urls.py`: normalisation table + extraction), 1 (`tests/test_items.py`: `capture_link` outcomes `new / existing / restored / archived`, `set_placement` stamping `trashed_at`), 6 (`tests/test_bot.py`: the seven bot behaviours). Design: `capture_link` returns a `Capture(item, outcome)` so the handler never inspects placement itself; only http(s) URLs are ever stored (`is_http_url` in extraction), which closes the `href` scheme concern deferred from ticket 01's review. The archived reply's `Вернуть` button carries `pl:<id>:active`; its handler lands with the rest of the Placement buttons in ticket 06. A resend never overwrites the existing Item's Annotation.

**Review (independent, read-only):** one high — a trailing `)` was stripped even when it closed a bracket inside the link (Wikipedia-style URLs got corrupted) → stripping is now bracket-balanced; two medium — guillemets `«»` glued to a link became part of it → excluded from the link and treated as punctuation; the dedupe was SELECT-then-INSERT and a double-send could raise on the unique index → `INSERT OR IGNORE` then read back, race-free by construction; one low — an explicit default port (`:443`, `:80`) produced a different key → default ports are dropped. All four covered by new tests in `tests/test_urls.py` (the race fix is covered by the existing new/existing tests, since the code path is now the same).
