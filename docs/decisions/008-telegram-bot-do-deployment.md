# ADR-008: Telegram bot interface + DigitalOcean deployment

Status: Accepted (2026-07-22). Amended 2026-09-13: `deploy.sh`'s allow-list also ships the `BOT_*` operator settings (ADR-004 amendment). Amended 2026-09-20: the allow-list gains `YTDLP_PROXY`, and an optional `warp` sidecar exists (ADR-014).

## Decision

1. Second interface `interfaces/telegram_bot` (ADR-005 thin adapter): aiogram 3
   long polling, stdlib sqlite (users / one-time invites / per-user settings /
   usage log), single FIFO worker = one job at a time, plus a `usage-dashboard`
   FastAPI entrypoint bound to localhost (SSH-tunnel access, no auth).
2. New top-level folder `infrastructure/` (user-approved exception to the
   three-folder layout; not scanned by `tools/check_layers.py`): Terraform
   (local state) provisions one DO droplet + SSH-only firewall; Docker Compose
   runs `bot` + `dashboard` from one image; sqlite on a named volume.
3. Access model: private bot; single admin (`ADMIN_TELEGRAM_ID`) mints one-time
   deep-link invites; redeemed users are whitelisted permanently in sqlite.
4. Local TTS backends are out of scope permanently — OpenAI speech only
   (the unimplemented `local_qwen3` surface was removed).

## Context

The bot must expose the same agents as the HTTP interface for ~1 concurrent
user at minimal cost. Env keys reuse the existing `.env` names verbatim
(`TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `DO_API_KEY` — the latter read only
by Terraform, never by app code).

## Consequences

- Usage DB and dashboard live inside the interface package; nothing in
  `shared/` gained dependencies.
- Deployment is push-based (`infrastructure/deploy.sh`: rsync + on-droplet
  `docker compose build`); no registry, no CI.
- Revisit if: >1 concurrent user (queue → parallel workers), webhook mode, or
  a second deployment target appears.
- Amended 2026-09-12 (security review): `deploy.sh` uploads an explicit key
  allow-list (`bot.env`) and the dashboard container carries no secrets; containers
  run read-only with memory/pid caps; the admin can `/revoke` a user; the bot
  answers private chats only.
