# 04 — Enrichment without an LLM

**What to build:** After a Link is saved, the bot fetches what the platform will give — YouTube, Instagram and TikTok through their oEmbed endpoints, everything else through a guarded generic page fetch — stores title, Source, author, caption and thumbnail, and edits the Acknowledgement to show them. Work is driven from the database: a background task for fresh Captures, a sweeper for retries with backoff and for anything a restart interrupted. The web shows the enriched fields and a failed badge with a re-enrich action. The Gist is a placeholder (first 200 characters of the caption) until the Classifier arrives.

**Blocked by:** 03 — Links with dedupe

**Status:** done (in maxi-notes, before the merge — ADR-015)

- [x] Each provider maps its saved fixture payload to the expected literal title, author and thumbnail; the Instagram provider extracts the caption text from the embed HTML (seam 3)
- [x] The SSRF guard refuses `http://169.254.169.254/`, `http://localhost/`, a `file:` URL and a URL with userinfo, and accepts a public hostname (seam 3)
- [x] With a failing HTTP client, the pipeline still marks the Item done with no caption and keeps it in Other; the Acknowledgement is edited to show the Source (seam 4)
- [x] A retryable failure schedules the next attempt at exactly `now + 1 min` on the first attempt and `now + 12 h` on the fifth; the sixth failure marks the Item failed with the error recorded (seams 1 and 4)
- [x] Due-work selection returns scheduled retries whose time has come and pending Items with no schedule older than two minutes, and nothing else (seam 1)
- [x] The web row shows title, author, thumbnail and the collapsed caption; a failed Item shows the error and a re-enrich control that flips it back to pending (seam 7)
- [ ] Manual: with a real bot token, a public YouTube link and a public Instagram reel show title/author (and caption for Instagram) in the edited Acknowledgement within seconds

## Comments

**2026-09-18 — implemented.** Seams: 3 (`tests/test_enrich_providers.py` over real responses captured once and trimmed into `tests/fixtures/`), 1 (`tests/test_items.py`: store / backoff / due-work / re-enrich / acknowledgement ids), 4 (`tests/test_pipeline.py`: pipeline outcomes and one sweep), 6 (`tests/test_bot.py`: a link is enriched in the background and its Acknowledgement edited), 7 (`tests/test_web.py`: enriched row; failed badge + re-enrich). **Half of the manual criterion is done without a token:** the real `AiohttpClient` was run through the pipeline against the live network for a YouTube link, an Instagram reel, a TikTok video, a blog page and the cloud metadata IP — all four providers returned title/author/thumbnail (and the caption for Instagram), the guard refused the metadata IP. The Telegram edit itself is covered at seam 6 with the recording session; seeing it in a real chat still needs the Owner's token.

**Findings that changed the design:** Meta's tokenless `instagram_oembed` returns only the bare embed markup (no author, caption or thumbnail; `fields=` demands an app id), so the Instagram provider reads the official **captioned embed page** instead — the document `embed.js` loads for any website, so it renders anonymously. ADR-0005 was corrected accordingly. YouTube watch pages exceed the 2 MB body cap, so oversized pages are now truncated rather than refused (the metadata sits in the head). The Classifier port (`FilingRequest` / `Filing` / error classes) landed here rather than in ticket 05 because the pipeline's retry/refusal branches are defined against it; ticket 05 adds the Claude adapter and the keyword-aware fake. Until then `CLASSIFIER_PROVIDER` defaults to `fake`.
