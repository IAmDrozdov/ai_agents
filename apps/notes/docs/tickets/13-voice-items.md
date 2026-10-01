# 13 — Voice Items: save, transcribe, file

**What to build:** ADR-0008. The admin's voice messages and round video messages (recorded in the bot or forwarded) are saved with no card as a Voice, transcribed during Enrichment, and filed with a Gist by the Classifier, which reads the Transcript. A forwarded Capture of any kind records its Sender.

**Blocked by:** 12 — Direct save for social links and files

**Status:** deployed 2026-10-01; live test green

**Checks** (no automated tests, ADR-001):
- [x] `notes-smoke --voice <a Russian .ogg>`: a readable Transcript, sensible Sections, Russian title and Gist (a synthesized Russian memo → Купить, «Купить беговые кроссовки»)
- [x] Migration: a file-era DB keeps its Items and Sections and accepts `kind='voice'`; running `init` twice is a no-op
- [x] Offline harness: admin voice / round video → "💾 Сохраняю…" then the Acknowledgement; a forwarded voice carries the Sender; an invitee's voice is ignored
- [x] Enrichment with a fake download stores the Transcript; a transient failure retries without losing the Item; a rejected download marks it failed
- [x] Admin photo, .pdf and a text card route as before
- [x] An article link card and a direct YouTube link route as before (live test, no Sender on own messages)
- [x] Deployed; a forwarded voice and a round video in Telegram get a Gist, and the Mini App shows the Transcript, duration and Sender (live test 2026-10-01)
