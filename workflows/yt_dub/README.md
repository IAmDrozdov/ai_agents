# yt_dub

Takes a YouTube URL, gets a transcript (captions first, audio + STT as fallback),
translates it, and synthesizes voice-over audio in the target language via OpenAI TTS.

## Pipeline

```
fetch_transcript (yt-dlp captions; marks needs_stt when there are none)
  → transcribe (audio download + shared.audio STT; pass-through when captions exist)
  → translate (shared.translate)
  → synthesize_audio (shared.audio)
```

Framework: LangChain — linear chain, no cycles (ADR-003 compliant). See
`docs/decisions/010-youtube-dubbing.md` for why captions-first, and
`docs/decisions/011-shared-audio-engine.md` for why the TTS/STT/Ogg engines live in
`shared.audio` rather than here.

`WORKFLOW.preview` runs only the fetch node (free, no download); the transcribe node
fires inside the graph during `run`, after the caller has confirmed the approximate
estimate (`Estimate.approximate` is true when transcription cost was inferred from
duration).

## No ffmpeg

Same constraint as `pdf_tts` (see its README's "Opus stitching" section) plus one
more: the audio-download fallback never transcodes. It picks the smallest
audio-only stream yt-dlp offers and sends the raw bytes straight to OpenAI's
transcription API. That API caps input at ~25 MB, so a video with no captions and
over roughly **65 minutes** of audio fails outright rather than being split —
splitting would need ffmpeg. Captioned videos have no such ceiling.

## Config knobs (`YtDubConfig`)

| Field | Default | Description |
|---|---|---|
| `speech` | `SpeechSpec()` | Same shared speech spec as `pdf_tts`; `spoken_language` defaults to the translation target |
| `translation` | `TranslateSpec()` | Source/target language, model, prices |
| `stt` | `SttSpec()` | STT model + price per minute (from `shared.pricing`) |
| `chapter_char_target` | `8000` | Size-based fallback chapter target |
| `max_document_chars` | `2,000,000` | Backstop against a huge transcript |
| `max_audio_bytes_for_stt` | `25 MB` | OpenAI's transcription input cap |
| `max_video_duration_s` | `4 hours` | Hard cap, checked before any download |
| `caption_languages` | `["en"]` | Tried after the video's own detected language |
| `chars_per_minute_estimate` | `900` | Used to price a no-captions video before transcription |

## Captions

`providers/youtube.py::fetch_captions` prefers a **manual** subtitle track over
**auto-generated** captions, tries the video's own language first and then
`caption_languages`, and reads the `json3` format when offered (falls back to
`vtt`). Deliberately does **not** use YouTube's own auto-translated (`tlang=ru`)
track — quality is well below `translate_chunks` and it would bypass the user's
own language settings.

## Result

Cost lines: `Transcription` (no-captions path only), `Translation`, `Speech`. Facts:
Transcript source, Chapters, Tokens, Chars billed, Chunks, Synthesis time.

## Smoke test

```bash
uv run smoke yt_dub https://www.youtube.com/watch?v=<id>
```

The preview and estimate probe metadata and fetch captions only — no paid API calls
until you confirm.

## Known risk: datacenter IP blocks

YouTube sometimes rejects requests from cloud/datacenter IPs with "Sign in to
confirm you're not a bot." `providers/youtube.py` surfaces this as a distinct,
readable error rather than a generic failure. The fix is `YTDLP_PROXY`, optionally
pointed at the bundled Cloudflare WARP sidecar — off by default, see ADR-014 and
`.env.example`.

## Legal note

The no-captions fallback downloads the audio track from YouTube, which is against
YouTube's Terms of Service; the captions path downloads no media. Whether to run this
workflow is the operator's own decision and risk (ADR-010).
