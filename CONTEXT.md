# Domain glossary

Terms used across code, docs and reviews. The notes app has its own glossary,
`apps/notes/CONTEXT.md`; its **Source** (the platform a Link came from) is not the **Source** below. Architecture vocabulary (module,
interface, seam, adapter, depth) is the `codebase-design` skill's; this file is the
product vocabulary.

- **Workflow** — a package under `workflows/` that turns a source into a deliverable
  for money. Exposed by exactly one descriptor, `WORKFLOW` (`shared.job.Workflow`),
  from its `runtime.py`. Composition lives in `graph.py`; steps are **nodes**.
- **Source** — what a user hands in: a `DocumentSource` (bytes + filename: PDF, DOCX,
  Markdown, text, or a scraped article) or a `LinkSource` (a YouTube URL). A
  workflow declares which kinds it **accepts**.
- **Preview** — the free, unbilled look at a source: title, character and chapter
  counts, optional duration and note, or an error. Carries a workflow-private
  **payload** that interfaces pass back untouched.
- **Estimate** — the pre-flight price of a preview: a **Cost** (total + named
  **cost lines**, e.g. Translation / Speech / Transcription) and whether it is
  approximate (no captions yet, so transcription cost is inferred from duration).
- **Result** — what a run returns: a **Deliverable** (`FileDeliverable` or
  `AudioDeliverable` with optional parts for splitting), the actual Cost, and
  ordered **facts** (label/value pairs) shown in the delivery caption.
- **Progress** — the object a run reports through: `phase(name, total)` when a stage
  starts, `tick(done, total)` as it advances.
- **Stage** — a shared provider-facing engine with a **spec**: translation
  (`TranslateSpec`), speech (`SpeechSpec`), transcription (`SttSpec`). Workflow
  configs compose specs; specs price themselves from the **pricing catalogue**
  (`shared.pricing`).
- **Document intake** — `shared.doc.parse_document`: bytes → text + chapters, memoised
  so one upload previewed by several workflows parses once.
- **Registry entry** — an interface's presentation record for one workflow: label,
  short label, which settings to show, and the settings → config builder. Never
  behaviour.
- **Job** — the bot's queue item: who, which workflow, its config and preview, and the
  status message to edit. One job runs at a time (ADR-008).
- **Estimate card** — the bot message listing priced actions for a pending source,
  with settings hints and an ETA per action. Its states are *live* (its intake may still
  edit it), *priced* (actions shown), *superseded* (a newer message's card opened in the
  chat; said as "⏭ Replaced…" if it was still pricing), *closed* (Cancel or 💾 took it) and
  *job* (Run accepted). Only a card that owns the chat's pending job can be run, re-priced
  or sent to Settings.
- **Draft** — the admin's text message held by its Estimate card until 💾 saves it as a
  Capture, Cancel or Run drops it, or a newer message supersedes the card
  (`telegram_bot.notes_capture.Draft`). Avoid: pending note, saved text.
- **Path** — the one thing an incoming bot message becomes: a card (for an agent document, or
  a link; the admin's single website link is savable), a Capture (text, file or voice; admin
  only), an "unsupported file type" answer, or nothing. Decided in one place,
  `telegram_bot/routing.py`. Avoid: route (noun), branch, handler choice.
- **Card book** — the bot's in-memory record of every chat's Estimate cards: which card is
  live, which card the chat's one pending job belongs to, and what 💾 would save for it
  (`telegram_bot/cards.py`). Lost on restart, which is why old buttons answer "expired".
  Avoid: pending dict, drafts, card state.
- **Savable** — the opaque attachment the admin's card carries for 💾; for notes it is a
  Draft. The card never looks inside it. Avoid: draft (when speaking of the card).
- **Smoke runner** — `interfaces/smoke`, the terminal adapter over the same contract
  and the workflow smoke surface (ADR-001; the other checks are in `docs/verifying.md`).
- **Mini App** — the admin's Telegram Mini App (`telegram_bot/miniapp`, ADR-016): a static shell
  plus a JSON API over notes and usage, opened from the 📒 menu button. Every API call carries
  Telegram-signed **initData**, and only `ADMIN_TELEGRAM_ID` passes.
- **Backup** — one day's off-droplet copy of everything the bot keeps: both databases, the bytes
  of every notes File and Voice, and a manifest. Say Backup, not dump, snapshot or export.
- **Settings vs Config** — `shared.config.Settings` is env/secrets; `<Name>Config`
  is workflow behaviour with code defaults (ADR-004).
