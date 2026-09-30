# Instagram, YouTube, TikTok links and files are saved with no card; the Classifier looks at the cover, then the captions

The admin's Instagram, YouTube and TikTok links, photos, videos and non-agent documents skip the
ask-first card and go straight to notes (`direct_link_handler`, `file_handler`). Scraping them for an
article was pointless: they are a reel, a post, a profile or a video. Agent documents (.pdf .docx .md
.markdown .txt) and every other link keep the card; invitees are unchanged.

Classification reads the caption and the Owner's words first. The cover or thumbnail always goes to
the model as a low-detail image. When the model answers `confident: false` for a YouTube video, it is
asked once more with the start of the video's captions (yt-dlp, no download). Files are `kind='file'`
with the Telegram `file_id` and a stored preview (`item_previews`).

## Considered Options

- Logging in to Instagram / YouTube for richer data — rejected: ADR-0005 forbids Instagram login (datacenter IP, `challenge_required` risk); public data covers what Filing needs.
- Downloading and transcribing Instagram / TikTok video — rejected: blocked from datacenter IPs and costly; caption plus cover is enough.
- Storing file bytes — rejected: Telegram already holds them; only a preview is kept.

## Consequences

- `items` was rebuilt once to widen the `kind` CHECK (`Database.init` migrates in place); back up `notes.sqlite3` before the first deploy.
- Instagram profile links are filed by username alone; private accounts still degrade to the Owner's words plus the cover.
