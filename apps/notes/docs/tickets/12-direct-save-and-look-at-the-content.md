# 12 — Direct save for social links and files, classify by caption then cover and captions

**What to build:** ADR-0007. Admin Instagram / YouTube / TikTok links, photos, videos and non-agent documents are saved with no card; the Classifier sees the cover image and, for an unsure YouTube video, its captions.

**Blocked by:** 05 — Filing and Gist by the Classifier

**Status:** implemented locally (2026-09-30); not deployed

**Checks** (no automated tests, ADR-001):
- [x] Offline harness: admin reel / youtu.be / TikTok / profile link → "💾 Сохраняю…" then the Acknowledgement, no scrape call
- [x] Admin article link keeps the card; an invitee's link keeps the card
- [x] Admin photo and .zip become `file` Items with a preview; a .pdf still reaches `document_handler`
- [x] Migration: an old-schema DB keeps its Items and Sections and accepts `kind='file'`; running `init` twice is a no-op
- [x] `notes-smoke` on YouTube sends the cover image (`image: yes`); captions fetch works
- [x] 11 Instagram links and 2 YouTube videos from the owner's Saved Messages through `notes-smoke`: Sections fit; a vague reel ("wishlist") became mugs → Buy only once the cover reached the model. A vague YouTube video (second pass with captions) not met yet
- [x] Deployed; the Mini App shows a photo preview and file name (previews were blocked by the CSP until `img-src blob:` on 2026-10-01)
