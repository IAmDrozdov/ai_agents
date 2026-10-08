# pdf_tts

Extracts text from a PDF, DOCX or Markdown document, optionally translates it, and synthesizes speech via the shared OpenAI TTS stage. Exposed as `pdf_tts.WORKFLOW` (ADR-012).

## Pipeline

```
extract_text (shared.doc.parse_document) → translate (optional, shared.translate) → synthesize_audio (shared.audio)
```

`graph.py` is the only composition; `runtime.py` holds the descriptor: `preview` parses
the document (free), `estimate` prices it with the stage estimators, `run` invokes the
graph and returns an `AudioDeliverable` + cost lines + facts.

Framework: LangChain — linear chain, no cycles (ADR-003 compliant).

## Config knobs (`PdfTtsConfig`)

| Field | Default | Description |
|---|---|---|
| `speech` | `SpeechSpec()` | Shared speech spec: `model`, `voice`, `spoken_language`, `instructions`, `chunk_size`, `output_format` (`opus`), `max_parallel`, `price_per_1k_chars` (follows the model via `shared.pricing`) |
| `translation` | `None` | `TranslateSpec` (`source_language`, `target_language`, `model`, `max_parallel`, prices) — set to translate before TTS; `speech.spoken_language` then defaults to its target language |
| `chapter_char_target` | `8000` | Size-based fallback chapter target |
| `max_document_chars` | `2,000,000` | Backstop against a huge document |

## Opus stitching

TTS runs chunk by chunk, so a document comes back as N standalone audio blobs. For
MP3 those can simply be concatenated, but Ogg-Opus cannot: byte-joining produces a
*chained* stream whose duration and seek bar only reflect chunk 1.

`shared.audio.concat_ogg_opus()` rewrites the container instead — one `OpusHead`/`OpusTags` pair,
one serial number, a continuous page sequence, and granule positions offset so
timestamps keep climbing. Packet payloads are never touched, so nothing is
re-encoded and no ffmpeg is required. Cost: each chunk boundary keeps ~6.5 ms of
pre-skip padding, which is inaudible in speech.

State keys: `audio_bytes`, `audio_parts` (per-chunk blobs, for size-limited
splitting downstream), and `audio_duration_s` — the playable length
in seconds, or `0.0` when unknown (only Opus is measured).

## Result

`Result.cost` lines: `Translation` (when enabled) and `Speech`. `Result.facts`:
Chapters, Tokens (when translated), Chars billed, Chunks, Synthesis time.

## Smoke test

```bash
uv run smoke pdf_tts path/to/document.pdf
uv run smoke pdf_tts path/to/document.pdf --config '{"translation": {"target_language": "German"}}'
```

Previews and prices first, asks before the paid run. Accepted file types: `.pdf`,
`.docx`, `.md`, `.markdown`, `.txt`.

DOCX known limits: body paragraphs only (tables, headers/footers, footnotes and
text boxes are skipped); non-English heading style names fall back to size-based
chapter splitting.
