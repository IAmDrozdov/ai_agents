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
- Snapshots of the Telegram tab dump the whole chat list. Save them with `filePath` under the
  repo's gitignored `.local/` (the MCP writes only inside the workspace), grep them, delete the
  named file afterwards.
- Telegram's buttons ignore a synthetic `.click()`: use the MCP `click` with a uid from a snapshot.
  The menu button shows up as `button "Open bot command keyboard"`.
- Forwarding: open the message's context menu (right-click, or hover → the arrow), choose Forward,
  pick the bot's chat. The forwarded copy reaches the bot with `forward_origin` set.
- The Mini App opens in an iframe modal, and the snapshot exposes its own controls, so `click` and
  `fill` work in place. Telegram's native confirm shows as a parent dialog with OK / CANCEL. The
  modal remembers a collapsed state: expand it, or reload the tab. Screenshot the app with
  `take_screenshot` on the iframe's uid (a full-page shot shows the owner's chat list).
- To drive the app top-level (a plain tab, easier to script), read the iframe `src` for the real
  `tgWebAppData` hash and open it in a new tab; that hash is the credential from the guardrails.
- The Acknowledgement is the bot's reaction on your message (✍ → 👌 or 👎, notes ADR-0009), and
  the bot sends no message: poll the snapshot every few seconds, up to a minute, until ✍ is gone.
- If this Mac is on the tailnet that publishes the Mini App, Chrome blocks the iframe (MagicDNS
  resolves to a private address): `tailscale set --accept-dns=false`, wait until the name no longer
  resolves to `100.x`, test, then `--accept-dns=true`.

## Cleanup
- Test messages (yours and the bot's, under 48 h old): `send_media.py delete <message_id…>`; the
  ids are in the snapshot or in `tg_message_id` of the Item (older Items also `tg_ack_message_id`).
- Test Items: Mini App → item → «В корзину», then Корзина → «Удалить навсегда».
