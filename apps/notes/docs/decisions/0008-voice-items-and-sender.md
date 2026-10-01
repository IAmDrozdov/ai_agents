# Voice is its own kind, transcribed during Enrichment; Sender is not Author; "show in chat" goes through the database

A voice message or a round video message sent to the bot becomes a **Voice**: `kind='voice'`, the
Telegram `file_id` (Telegram keeps the bytes) and a **Transcript** in its own column. The Item is
saved and Acknowledged first (ADR-0006); Enrichment downloads the audio through a `download`
callable the bot passes in (notes never imports aiogram), transcribes it with `shared.audio`, stores
the Transcript at once and then asks the Classifier. The Transcript is derived data: the Owner never
edits it, and a re-enrich regenerates it. `text` stays the Annotation, as on Links and Files.

A forwarded Capture of any kind records its **Sender** (person, hidden user, chat or channel).
Author keeps meaning the maker of a Link's content, still filled by Enrichment.

Every Item now remembers its original `tg_message_id`. "💬 Показать в чате" in the Mini App sets
`show_requested_at`; a 2-second loop in the bot process replies to that message (the reply's quote
jumps to it) or, if it is gone, sends a Voice or File again by `file_id`.

## Considered Options

- Voice as a Note whose text is the Transcript — rejected: STT gets names and mixed-language terms wrong, and with the audio gone there is nothing to check against; a forwarded voice is not the Owner's words either.
- Voice as a File — rejected: File means "classified by its preview image"; a voice has none, and its content is the Transcript.
- Transcribe in the handler before saving — rejected: breaks "nothing thrown at the bot is lost" (ADR-0006) whenever STT or Telegram is down.
- The forwarder as Author — rejected: for a forwarded Link the forwarder is not the maker, and Enrichment would overwrite them.
- The bot token in the miniapp container, or an internal HTTP endpoint in the bot, for "show in chat" — rejected: the miniapp is reachable from the internet through Funnel (ADR-016); the database queue costs a 2-second delay and no new channel.
- A deep link to the original message — impossible: `t.me/c/…` links exist only for supergroups and channels, not a private chat with a bot.

## Consequences

- `items` was rebuilt again to widen the `kind` CHECK and add `duration_s`, `transcript`, `sender`, `tg_message_id`, `show_requested_at`; back up `notes.sqlite3` before the first deploy.
- Items saved before this have no `tg_message_id`, so the Mini App shows no "Показать в чате" for them.
- A Voice over Telegram's 20 MB download limit (about two hours of speech) fails Enrichment and stays in Other. `audio` messages and audio documents are still Files.
