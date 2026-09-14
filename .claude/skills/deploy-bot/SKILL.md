---
name: deploy-bot
description: Deploy the current code to the Telegram bot droplet and verify it is healthy. Use when the user says "deploy", "deploy the bot", "ship it", or after changes to workflows/interfaces need to go live.
---

# Deploy the Telegram bot to the DigitalOcean droplet

Push-based deploy: rsync the repo to the droplet, build the Docker image there,
restart both containers (`bot`, `dashboard`), then verify. Full infra docs:
`infrastructure/README.md` (ADR-008).

## Preconditions

- `.env` at repo root has `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`.
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
   Takes ~1–3 min (rsync + on-droplet `docker compose build` + `up -d`).
   If the on-droplet build OOMs or fails, use the buildx fallback in
   `infrastructure/README.md`.

3. **Verify** (all over SSH; IP from terraform output):
   ```bash
   IP=$(terraform -chdir=infrastructure/terraform output -raw droplet_ipv4)
   ssh ${SSH_KEY:+-i "$SSH_KEY"} root@$IP 'docker ps --format "{{.Names}}: {{.Status}}"'
   ssh ${SSH_KEY:+-i "$SSH_KEY"} root@$IP 'docker logs docker-bot-1 2>&1 | tail -5'
   ssh ${SSH_KEY:+-i "$SSH_KEY"} root@$IP 'curl -s http://127.0.0.1:8081/healthz'
   ```
   Expected: both containers `Up`; bot log ends with
   `polling as @<your-bot-username>` and `worker loop started` (no tracebacks);
   healthz returns `{"status":"ok"}`.

4. **Report** — state what was deployed (branch/diff summary), the verification
   results, and the dashboard tunnel command:
   `ssh ${SSH_KEY:+-i "$SSH_KEY"} -N -L 8081:127.0.0.1:8081 root@$IP`

## Rollback

The droplet has no git history — rollback is redeploying older code from your machine:
```bash
git stash            # or check out the last good commit
./infrastructure/deploy.sh
git stash pop
```
The sqlite volume (`/data/telegram_bot.sqlite3`) is untouched by deploys; users,
settings, and usage history survive. Back it up before schema-affecting changes:
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
