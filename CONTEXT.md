# Domain glossary

Terms used across code, docs and reviews. Architecture vocabulary (module,
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
  with settings hints and an ETA per action.
- **Smoke runner** — `interfaces/smoke`, the terminal adapter over the same contract
  and the only verification surface (ADR-001).
- **Settings vs Config** — `shared.config.Settings` is env/secrets; `<Name>Config`
  is workflow behaviour with code defaults (ADR-004).
