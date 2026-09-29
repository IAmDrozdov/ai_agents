# ADR-016: A Telegram Mini App replaces the SSH-tunnel web UIs

Status: Accepted (2026-09-29). Supersedes notes ADR-0004; amends ADR-008 (the dashboard) and ADR-015 (decision 3).

## Context

The usage dashboard (`127.0.0.1:8081`) and the notes web UI (`127.0.0.1:8082`) were reachable
only through an SSH tunnel and had no authentication, so the owner could not use them from a
phone. The owner wanted one entry point inside Telegram that knows about both notes and usage.
Notes ADR-0004 had named a Mini App as the v2 candidate and rejected it for v1 only because it
needs public HTTPS.

## Decision

1. **One Russian admin Mini App** (notes browsing and sorting, Section management, usage)
   replaces `dashboard` and `notes-web`. Both services, the `usage-dashboard` script and the
   `interfaces/notes_web` package are deleted.
2. **Where it lives.** `interfaces/telegram_bot/src/telegram_bot/miniapp/`: Telegram-specific
   transport that reuses `telegram_bot.db` and the notes app (ADR-005). It runs as its own
   `miniapp` service (`telegram-miniapp`, `127.0.0.1:8083`): a public static shell (vanilla JS,
   no build step) plus a JSON API under `/api`. Domain rules stay in `apps/notes`.
3. **Auth.** Every `/api` call carries `Authorization: tma <initData>`. The server checks
   Telegram's HMAC (only `hash` is left out of the check string), requires `auth_date` to be at
   most 24 h old, and admits only `ADMIN_TELEGRAM_ID`: 401 for unsigned or stale data, 403 for
   anyone else. There are no cookies, so there is no CSRF surface. The shell and `/healthz` are
   public and hold no data. The container holds `MINIAPP_INIT_SECRET`, which is
   HMAC-SHA256("WebAppData", bot token) derived by `deploy.sh`, so a compromised public
   container cannot act as the bot. There is no TrustedHost check: DNS rebinding cannot forge a
   signature, and a proxy-rewritten Host header would only break the app.
4. **Ingress.** A `funnel` sidecar (compose profile `funnel`, the `tailscale/tailscale` image
   in userspace mode) publishes `miniapp` at `https://ai-agents.<tailnet>.ts.net` through
   Tailscale Funnel. It connects outbound only, so the firewall stays SSH-only.
   `BOT_MINIAPP_URL` may point at any other HTTPS reverse proxy of `127.0.0.1:8083`.
5. **Entry points.** The admin's chat gets a per-chat menu button `📒`, set at bot
   startup (invitees keep the default menu). Each saved-item message gets `✏️ Открыть`, a
   `web_app` button that opens the item (`/?item=<id>`; never a `#fragment`, because Telegram
   puts its launch data there).
6. **Backlog.** Notes tickets 06 (chat keyboard) and 07 (`/list`) are replaced by the app. 08
   (sorting pass) and 09 (Section management) are built in the app instead of on the web UI.

## Consequences

+ Usage and notes are one tap from the chat, on the phone.
+ Two fewer services and less memory; the new `funnel` sidecar uses about 25 MB.
- A public HTTPS surface guarded by one signature check.
- A Tailscale account is required, and the node's key expiry must be disabled, or the app stops
  loading after about 180 days.
- The app works only inside Telegram; there is no browser fallback.
- Acknowledgement messages in the chat are snapshots: an edit in the app does not re-render
  them. `✏️ Открыть` always opens the live state.
- The Mini App process can write both sqlite files, as `notes-web` could.
