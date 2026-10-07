# A card shows a Thumbnail kept in sqlite, never a third-party cover

A card used to load the Link's cover straight from its site, at full size, into a 72 px slot.
Instagram cover URLs are signed and expire after 4–7 days: by 2026-10-07, 11 of 19 returned 403, and
those cards showed a broken picture. The covers that still worked weighed 1.9 MB for 8 cards, one of
them 957 KB.

Now Enrichment makes a **Thumbnail**: a 216 px square (3× the slot), centre-cropped, WebP, about
6 KB. It is cut from the cover the Classifier already downloads (Links), or from the stored preview
(Files and round videos). It is kept in `item_thumbs` with its etag. It is made before classifying,
so a failed Filing still leaves the card its picture. A re-enrich replaces it. The Mini App fetches
`/api/notes/items/{id}/thumb?v=<etag>`, which the webview caches for good
(`private, max-age=31536000, immutable`). The bot backfills Items that have none at every start, and `notes-thumbs` does the same by hand.
An expired cover URL is fetched fresh from the provider, with no Classifier call.

## Considered Options

- Hot-linking the cover — rejected: it expires, it is heavy, and it reveals the Owner's Links to every CDN.
- Keeping the full cover — rejected: up to 1 MB each for a 72 px picture.
- A resizing proxy (wsrv.nl and the like) — rejected: a third party would see every cover, and it still breaks when the URL expires.
- Files on the volume — rejected: one more thing to back up and keep in step. sqlite reads small blobs faster than separate files (sqlite.org, "Internal Versus External BLOBs").

## Consequences

- `apps/notes` depends on Pillow. Decoding is capped at 16 Mpx: a 150 KB PNG can be 40 Mpx, about 650 MB to decode. A JPEG decodes at a reduced scale, and any decoding error just means no Thumbnail. The bot container is hardened, as it is for PDFs.
- About 6 KB per Item: roughly 22 MB a year at 10 Items a day, inside the daily Backup (ADR-018).
- The preview stays as it was: the Classifier's vision needs more than 216 px.
- A Link with no cover, a plain Note and a voice message have no Thumbnail, so their cards have no picture.
