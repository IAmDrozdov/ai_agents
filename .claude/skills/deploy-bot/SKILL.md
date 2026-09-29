---
name: deploy-bot
description: Deploy the current code to the Telegram bot droplet and verify it is healthy. Use when the user says "deploy", "deploy the bot", "ship it", or after changes to workflows/interfaces need to go live.
---

# Deploy the Telegram bot to the DigitalOcean droplet

Push-based deploy: rsync the repo to the droplet, build the Docker image there,
restart the containers (`bot`, `miniapp`; `funnel` and `warp` when enabled), then verify.
Full infra docs: `infrastructure/README.md` (ADR-008); what each service does:
`docs/runtime.md`.

## Preconditions

- `.env` at repo root has `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`. Only the
  allow-listed keys reach the droplet (`deploy.sh`); a new env var needs the regex there too.
- Optional Mini App publishing: `TS_AUTHKEY` and `BOT_MINIAPP_URL` in `.env` (Tailscale Funnel; the
  one-time owner steps are in `infrastructure/README.md`), and `python3` on your PATH, because
  `deploy.sh` derives the Mini App's key from the bot token locally.
- `infrastructure/terraform/terraform.tfvars` names your DO SSH key (`ssh_key_name`);
  optionally `export SSH_KEY=~/.ssh/<key>` for the matching private key (unset means
  ssh-agent / `~/.ssh/config`).
- Droplet exists: `terraform -chdir=infrastructure/terraform output -raw droplet_ipv4`
  (if it errors, provision first per `infrastructure/README.md`).
- NEVER run `uv run telegram-bot` locally while the droplet bot is up — two
  pollers on one token fight over getUpdates (Telegram 409 Conflict).

## Steps

1. **Gate** — run and require green before deploying:
   ```bash
   uv run pre-commit run --all-files
   ```
   (ruff fix+format, ty, layer checker. Fix violations; never deploy red.)

2. **Deploy**:
   ```bash
   ./infrastructure/deploy.sh
   ```
   Takes ~2–4 min (rsync + on-droplet `docker compose build` + `up -d`). It waits for the bot
   and the Mini App, then checks the public Mini App URL when Funnel is on (a warning, not a
   failure: the first certificate can take minutes). A failed build stops before `up -d`, so the
   old containers keep running.
   If the on-droplet build OOMs or fails, use the buildx fallback in
   `infrastructure/README.md`.

3. **Verify** (all over SSH; IP from terraform output):
   ```bash
   IP=$(terraform -chdir=infrastructure/terraform output -raw droplet_ipv4)
   ssh ${SSH_KEY:+-i "$SSH_KEY"} root@$IP 'docker ps --format "{{.Names}}: {{.Status}}"'
   ssh ${SSH_KEY:+-i "$SSH_KEY"} root@$IP 'docker logs docker-bot-1 2>&1 | tail -5'
   ssh ${SSH_KEY:+-i "$SSH_KEY"} root@$IP 'curl -s http://127.0.0.1:8083/healthz'
   curl -s "$BOT_MINIAPP_URL/healthz"   # public, when Funnel is on
   ```
   Expected: all containers `Up`; bot log ends with
   `polling as @<your-bot-username>` and `worker loop started`, with no tracebacks and no
   `notes disabled`; healthz returns `{"status":"ok"}`. For regression checks that cost
   nothing (agent previews in the new image, `notes-smoke`), see `docs/verifying.md` §4; the
   real-chat check in Telegram Web is `docs/verifying.md` §5.

4. **Report** — state what was deployed (branch/diff summary), the verification
   results, and the Mini App URL (`BOT_MINIAPP_URL`): the owner opens it with the 📒 button in
   the bot chat.

## Rollback

The droplet has no git history — rollback is redeploying older code from your machine.
Before a risky deploy, tag the running image (`docker tag ai_agents:latest ai_agents:rollback-<n>`
on the droplet): `docker image prune -f` keeps tagged images.
```bash
git stash            # or check out the last good commit
./infrastructure/deploy.sh
git stash pop
```
The sqlite volume (`/data/telegram_bot.sqlite3`, `/data/notes.sqlite3`) is untouched by
deploys; users, settings, usage history and notes survive. `notes.sqlite3` is WAL with two
writers, so back it up with the snapshot command in `infrastructure/README.md`. Back it up before schema-affecting changes:
```bash
ssh ${SSH_KEY:+-i "$SSH_KEY"} root@$IP \
  'cat $(docker volume inspect -f "{{.Mountpoint}}" docker_appdata)/telegram_bot.sqlite3' > backup.sqlite3
```

## If a running job would be interrupted

`docker compose up -d` restarts containers, killing any in-flight job (the job
row stays `running` in the usage log). For a private ~1-user bot this is usually
fine; if the user cares, check first:
```bash
ssh ${SSH_KEY:+-i "$SSH_KEY"} root@$IP 'docker logs docker-bot-1 2>&1 | tail -3'
```
and deploy when no job is mid-run.
