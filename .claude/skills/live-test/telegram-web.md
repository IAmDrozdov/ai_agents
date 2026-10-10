# Driving Telegram Web for a live test

The real chat is the owner's: real data, a real account. Machine facts (which Chrome profile, the
bot chat's URL) live in `CLAUDE.local.md`, which is gitignored because this repo is public.

## Guardrails
- Attach through the `chrome-devtools` MCP (`--autoConnect`). The browser it attaches to is the
  owner's Main profile, logged in everywhere; work-titled tabs there are still Main. Open the tabs
  you need yourself (`new_page` with the bot chat's URL from `CLAUDE.local.md`) instead of asking
  the owner. Work only in the tabs you opened or the Telegram Web / Mini App tab; leave the owner's
  other tabs alone. A login QR still means the wrong profile: stop and report.
- Send only `🧪`-labelled content, and never tap Run on an agent card (paid).
- Mini App `initData` read from the page is an admin credential for 24 h: keep it under `.local/`,
  never print or commit it.

## Mechanics
- One tab per run. Start with a single `list_pages`: it fails fast when the DevTools attach is
  down, where `new_page` hangs for its full timeout; then drive the run with the `claude-in-chrome`
  tools instead (`browser_batch` chains several actions in one call) and say so in the result.
  Otherwise open the bot chat once with `new_page`, keep its page id, and reload with
  `evaluate_script(() => location.reload())`: every `list_pages`, `new_page`, `select_page` or
  `close_page` prints all of the owner's open tabs (3.5-4.6k tokens).
- Snapshots of the Telegram tab dump the whole chat list. Save them with `filePath` under the
  repo's gitignored `.local/` (the MCP writes only inside the workspace) and read them with
  `python3 .claude/skills/live-test/snap.py iframe <file> [regex]` (the Mini App subtree) or
  `snap.py grep <file> <regex>` (the whole page), or `snap.py uid <file> <regex>` for just the
  `uid label` pairs to click: uids included, URLs masked, output capped. Delete
  the named file afterwards. Do not wait with `wait_for`: it returns the whole snapshot inline, and
  with the Mini App open that includes the iframe `src` with its `tgWebAppData`. Poll with
  `take_snapshot` and `filePath` instead.
- Every snapshot excerpt, screenshot (~1.6k tokens) and log line stays in context for the rest of
  the run and is re-read on each later call. Screenshot only a case's checkpoint, keep evidence as
  file paths, and read an image back only when the case needs a visual judgement.
- Telegram's buttons ignore a synthetic `.click()`: use the MCP `click` with a uid from a snapshot.
  The menu button shows up as `button "Open bot command keyboard"`.
- Forwarding: open the message's context menu (right-click, or hover → the arrow), choose Forward,
  pick the bot's chat. The forwarded copy reaches the bot with `forward_origin` set.
- The Mini App opens in an iframe modal, and the snapshot exposes its own controls, so `click` and
  `fill` work in place. Telegram's native confirm shows as a parent dialog with OK / CANCEL; its back
  button and main button («✓ Готово» on the Item view, ADR-021) are parent-page controls too. The
  modal remembers a collapsed state: expand it, or reload the tab. Screenshot the app with
  `take_screenshot` on the iframe's uid (a full-page shot shows the owner's chat list).
- To drive the app top-level (a plain tab, easier to script), read the iframe `src` with
  `evaluate_script` (`snap.py` masks it in snapshots) and open it in a new tab; its `tgWebAppData`
  hash is the credential from the guardrails.
  `list_pages`, `select_page` and `navigate_page` print every tab's full URL, so strip the hash at
  once in the new tab (`history.replaceState(null, "", location.pathname + location.search)`;
  `telegram-web-app.js` has already read it). Outside Telegram, `DeviceStorage` never answers; and
  Telegram Web answers it `UNSUPPORTED`. So the app keeps its snapshot in `localStorage` there.
- The Acknowledgement is the bot's reaction on your message (✍ → 👌 or 👎, notes ADR-0009), and
  the bot sends no message. Wait for it in the page: one `evaluate_script` that polls the DOM every
  2 s for up to 60 s and returns the reactions on your last message (reading the DOM works; only
  clicks are ignored). Once a selector is confirmed, write it here so the next run reuses it.
- If this Mac is on the tailnet that publishes the Mini App, Chrome blocks the iframe (MagicDNS
  resolves to a private address): `tailscale set --accept-dns=false`, wait until the name no longer
  resolves to `100.x`, test, then `--accept-dns=true`.

## Cleanup
- Test messages (yours and the bot's, under 48 h old): `send_media.py delete <message_id…>` takes
  **Bot API** ids. Telegram Web's own ids (`data-message-id`, six digits in a private chat) are a
  different numbering and fail with "message to delete not found". Read `tg_message_id` of the Item
  (older Items also `tg_ack_message_id`) before the case deletes the Item; a message with no Item
  goes through the web context menu «Удалить» instead.
- Test Items: Mini App → «Заметки · записи» → «🔍» → `🧪` → the row's «⋮» → «🗑 Удалить», then confirm (Search covers both Statuses).
