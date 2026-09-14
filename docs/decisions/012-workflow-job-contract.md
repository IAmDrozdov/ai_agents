# ADR-012: One workflow job contract; interfaces hold registries

Status: Accepted (2026-09-12)

## Decision

1. Every workflow package exports one descriptor, `WORKFLOW: shared.job.Workflow`,
   from its `runtime.py`: `id`, `config_type`, `accepts` (source kinds),
   `preview(settings, config, source)`, `estimate(settings, config, preview)`,
   `run(settings, config, preview, progress)`, `speed_profile(config)`. The types
   (`Source`, `Preview`, `Estimate`, `Result`, `Deliverable`, `Cost`/`CostLine`,
   `Fact`, `Progress`) live in `shared/job.py` as plain dataclasses — no LangChain in
   the contract.
2. `preview` is free and unbilled (parse the document, fetch captions). It returns a
   uniform header for cards plus an opaque `payload` the interface passes back
   untouched. `estimate` prices that preview with the same stage estimators the run
   uses. `run` returns a typed deliverable (`FileDeliverable` | `AudioDeliverable`),
   named cost lines, and ordered facts for captions. Interfaces never read state
   dicts or stats keys.
3. `graph.py` is the single composition per workflow and takes the `Progress`
   object; node builders are `build_<node>_node(settings, config, progress)`. The
   descriptor's `run` is `build_graph(...).invoke(...)` plus one mapping into
   `Result`. There is no second hand-composed runtime path.
4. Provider stages are shared and spec-driven: `shared.translate.translate_chunks`
   (`TranslateSpec`), `shared.audio.synthesize` (`SpeechSpec`),
   `shared.audio.transcribe` (`SttSpec`). Workflow configs compose these specs
   instead of flattening their fields; values still default in workflow code
   (ADR-004 holds). Each stage returns its own `CostLine`, so estimate and actual
   cost are computed by one module per stage.
5. `shared.pricing` is the one price catalogue (model ids, labels, prices, voices).
   Specs default their prices from it; the bot's settings menu reads its option
   lists from it. This supersedes ADR-011's consequence that each workflow keeps its
   own `TTS_MODEL_PRICES` table.
6. Document intake (`shared.doc.extract.parse_document`) lives in `shared`, with a
   small memo keyed by content hash + chunking knobs, so previewing one upload for
   several workflows parses it once. `shared` therefore declares `pypdf` and
   `python-docx`.
7. Interfaces hold a registry of presentation-only entries per workflow (labels,
   which settings to show, settings → config builder). Behaviour is never in the
   registry. The Telegram bot has `telegram_bot/registry.py`; the smoke runner
   (`interfaces/smoke`) has its own three-line list.
8. `interfaces/smoke` is the second adapter on the contract and the ADR-001 smoke
   surface: `uv run smoke <workflow> <path-or-url>` previews, prices, asks before
   paying, runs with progress, and writes the deliverable. Per-workflow
   `examples/run.py` scripts are gone.

## Context

An architecture review on 2026-09-12 found every runtime presenting the same shape
by convention only: parameter names, stats keys and output shapes differed, so the
bot re-derived "how to preview, price, run and deliver workflow X" in eleven
per-agent switch points, `stats["estimated_cost_usd"]` meant "total" in one workflow
and "translate-only" in another, extraction was a 140-of-153-line clone, price
tables lived in four places, and `yt_dub`'s graph had already diverged from its
runtime. Onboarding `yt_dub` (ADR-010) touched all of it and needed its own intake
path. The owner chose the deepest cut: contract + shared stages + single
composition in one change.

## Consequences

- A new workflow = a package exporting `WORKFLOW` + one registry entry in the bot
  (label, short label, hint keys, config builder). Nothing else in the bot changes.
- Cost has one meaning everywhere: the sum of stage cost lines. The usage log
  stores `cost_usd` and `stats_json = {cost, facts}`; the `input_tokens`,
  `output_tokens` and `tts_chars_billed` columns remain for old rows but are no
  longer written.
- `speed_profile` replaces the bot's per-agent ETA key logic; rows written before
  this change carry the old flat config shape and only feed the per-workflow rate.
- The TTS instructions prompt is derived inside `SpeechSpec` from `spoken_language`;
  the interface no longer composes prompt text (ADR-005).

## Revisit when

- A workflow needs a source kind other than a document or a link (e.g. free text):
  extend `SourceKind` and `Source`, not the interfaces.
- A deliverable type other than a file or audio appears.
