# ADR-011: TTS/STT/Ogg engines live in `shared.audio`

Status: Accepted (2026-09-11). Amended 2026-09-13: `workflows/repo_qa` (mentioned under `stt.py`) was deleted the next day by ADR-013.

## Decision

Move the TTS synthesis engine and the Ogg/Opus container stitcher out of
`pdf_tts` (where they were the only consumer) into `shared.audio`, alongside
a new `shared.audio.stt.transcribe`. `pdf_tts`'s and `yt_dub`'s
`nodes/synthesize_audio.py` become thin wrappers that map their own
workflow config onto `shared.audio.synthesize_chunks(...)`.

- `shared/audio/tts.py` — `synthesize_chunks(...)`, parallel OpenAI TTS with
  first-error-abort/cancel, unchanged from its `pdf_tts` original.
- `shared/audio/ogg_opus.py` — `concat(...)`, the pure-stdlib Ogg-Opus
  container rewrite, moved verbatim.
- `shared/audio/stt.py` — `transcribe(...)`, generalized from
  `repo_qa.runtime.transcribe_question` (which repo_qa keeps its own copy of;
  it is no longer a bot dependency and this ADR does not touch it).

## Context

`yt_dub` needs the same TTS engine `pdf_tts` already has, plus STT for its
no-captions fallback. `workflows/<a>/*` may not import `workflows/<b>/*`
(layer rules, `tools/check_layers.py`), so duplicating ~380 lines of TTS +
Ogg-container code into a second workflow was the alternative. ADR-007 set
the precedent for this shape: a provider-facing engine belongs in `shared`,
with each workflow's `config.py` and thin nodes owning only its own knobs
(`shared.translate.translate_chunks` already works this way).

## Consequences

- `pdf_tts.ogg_opus` is deleted; every caller (its own node,
  `telegram_bot.worker`'s part-splitting) now imports `shared.audio`.
- `pdf_tts.PdfTtsState`/`PdfTtsStats` keys and `pdf_tts.runtime.synthesize_text`'s
  signature are unchanged — this is an internal move, not a behavior change.
- `yt_dub.config.YtDubConfig` still duplicates the small `TTS_MODEL_PRICES`
  constant table that `pdf_tts.config` also has — cross-workflow imports are
  forbidden, so each workflow's own pricing knobs stay wherever ADR-004
  already puts them; only the engine that spends them moved.

## Revisit when

A third audio-producing workflow needs a knob `synthesize_chunks` doesn't
expose yet — extend the shared function's parameters rather than
reintroducing a workflow-local copy.
