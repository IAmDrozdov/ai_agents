# 11 — Mini App walking skeleton

**What to build:** The admin's chat gets a `📒` menu button that opens the Mini App (ai_agents ADR-016): a Russian app with a Заметки tab (Section chips, Активные / Архив / Корзина, item cards, re-enrich) and a Расходы tab (the retired dashboard's totals, per-user spend and job history). The Tailscale Funnel sidecar publishes it over HTTPS, and every `/api` call needs Telegram-signed data from the admin. The SSH-tunnel `dashboard` and `notes-web` services are retired.

**Blocked by:** 05 — Filing and Gist by the Classifier

**Status:** done (deployed 2026-09-29; checked with signed requests, on the droplet, and in Telegram Web)

- [ ] `/api/usage` and `/api/notes/*` answer 401 without a header, with a tampered hash, and with an `auth_date` older than 24 h; 403 for a valid signature of another user id; 200 for the admin
- [ ] Filtering by two Sections lists Items in either; `placement=archived` and `trashed` list only those; the default lists active Items with done ones last; `total` and paging (50 per page) are right
- [ ] The Section counts on the chips equal the active Items per Section
- [ ] «Разобрать заново» on a failed Item turns it `pending` and clears its error
- [ ] Расходы shows the same totals as the retired dashboard did for the same database
- [ ] After a bot restart the admin's menu button is the Mini App when `BOT_MINIAPP_URL` is set and the default menu when it is empty; an invitee's menu never changes
- [ ] `curl $BOT_MINIAPP_URL/healthz` answers from the internet while the droplet still accepts inbound SSH only
- [ ] No string from the database or a remote site is inserted as HTML (`textContent` only), and the CSP forbids inline script
