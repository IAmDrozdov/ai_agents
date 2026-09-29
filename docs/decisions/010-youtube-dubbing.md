# ADR-010: YouTube dubbing (`yt_dub`)

Status: Accepted (2026-09-11). Amended 2026-09-13: the dub target language is a per-user setting defaulting to `BOT_DEFAULT_TARGET_LANGUAGE`; "Russian" below was the original operator's default. Amended 2026-09-20: the block in §5 occurred; ADR-014 adds the optional egress proxy.

## Decision

1. New workflow `yt_dub`: YouTube URL → Russian voice-over audio, delivered
   through the Telegram bot the same way `pdf_tts` delivers a document
   (voice message, split into parts past Telegram's 50 MB cap).
2. Transcript source is **captions-first**: `yt-dlp` fetches manual
   subtitles, falling back to auto-generated captions, before anything is
   downloaded or billed. Only when no caption track exists in a preferred
   language does the workflow fall back to downloading audio and
   transcribing it with OpenAI STT.
3. **No ffmpeg.** The audio-download fallback picks the smallest audio-only
   stream yt-dlp offers and sends it to OpenAI's transcription API
   unmodified. That API caps input at ~25 MB, so a no-captions video over
   roughly 65 minutes fails outright with a clear message rather than being
   split — splitting would need ffmpeg, which this deployment deliberately
   does not have (ADR-008).
4. `yt-dlp` over `youtube-transcript-api` or similar: yt-dlp already handles
   video metadata, format selection and the anti-bot request signing that a
   caption-only library would have to duplicate, and it is the same tool the
   audio-download fallback needs regardless.
5. Datacenter IP blocks are a known, accepted risk, not solved up front.
   YouTube sometimes rejects cloud-host requests ("Sign in to confirm you're
   not a bot"). `providers/youtube.py` recognizes this case and returns a
   distinct, readable error. A cookies file or proxy would fix it but is
   deferred until it actually happens in production — adding either before
   there is evidence of a block is premature complexity for a
   single-user bot.

## Context

The user wanted: paste a YouTube link into the Telegram bot, get back Russian
voice-over audio, for long-form material (podcasts, lectures, 1h+). The
pipeline from "source text" onward already existed (`pdf_tts`'s
translate → TTS chain, lifted into `shared.audio` per ADR-011); the only new
work is getting a transcript out of YouTube without a paid API call before
the user has confirmed the cost.

## Consequences

- No new cost for videos that already have captions — the common case for
  podcasts and lectures — and no dependency on OpenAI STT at all in that
  path.
- Downloading YouTube audio is against YouTube's Terms of Service. This is a
  personal-use, single-admin-invited bot (ADR-008 access model), not a
  public or redistributed service; the owner accepts that risk knowingly.
- yt-dlp tracks YouTube's frontend closely and goes stale when YouTube
  changes its page format. When extraction starts failing in production,
  the fix is a dependency bump + redeploy, not a code change.
- `max_video_duration_s` (4h default) and `max_audio_bytes_for_stt` (25 MB)
  are hard backstops in `YtDubConfig`, on top of the bot's existing
  `MAX_JOB_COST_USD` / `DAILY_USER_COST_LIMIT_USD` guards.

## Revisit when

- A datacenter IP block actually occurs in production → add a cookies file
  (documented in the deploy skill) or a proxy.
- A no-captions video regularly exceeds the 65-minute STT ceiling → consider
  adding ffmpeg to the image (weigh against the droplet's 1 vCPU / 1 GB +
  2 GB swap budget) to split audio before transcription.
