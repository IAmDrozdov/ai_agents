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
- `.env` also has `DO_API_KEY`: the droplet's SSH port is closed, and `deploy.sh` opens it for
  this machine's address through `infrastructure/ssh-gate.sh` (ADR-017). A plain `ssh root@<ip>`
  times out; every SSH command below goes through the gate.
- `trufflehog` and `grype` are installed (`brew install trufflehog grype`): the deploy preflight.
- Optional Mini App publishing: `TS_AUTHKEY` and `BOT_MINIAPP_URL` in `.env` (Tailscale Funnel; the
  one-time owner steps are in `infrastructure/README.md`), and `python3` on your PATH, because
  `deploy.sh` derives the Mini App's key from the bot token locally.
- `infrastructure/terraform/terraform.tfvars` names your DO SSH key (`ssh_key_name`);
  optionally `export SSH_KEY=~/.ssh/<key>` for the matching private key (unset means
  ssh-agent / `~/.ssh/config`).
- Droplet exists: `terraform -chdir=infrastructure/terraform output -raw droplet_ipv4`
  (if it errors, provision first per `infrastructure/README.md`).
- Keep `uv run telegram-bot` off this machine while the droplet bot is up: two pollers on one
  token fight over getUpdates (Telegram 409 Conflict).

## Steps

0. **Before** — `./infrastructure/droplet.sh status` must show every container `Up` and `jobs
   running: 0`: the restart kills an in-flight job (its row stays `running`). Before a
   schema-affecting change, take a Backup (ADR-018):
   `SSH_KEY=~/.ssh/<key> uv run python infrastructure/backup.py run --force`.

1. **Gate** — green before deploying, as in `CLAUDE.md` "Validation before finishing": ruff fix and
   format on the changed files, then pre-commit with its exit code checked (ruff, ty, layer checker,
   secrets scan; never deploy red). Run `git status` too: `deploy.sh` ships the working
   tree, so another session's uncommitted work would go out with yours.

2. **Deploy** — one blocking call that keeps the full log in a file and prints only the step lines:
   ```bash
   ./infrastructure/deploy.sh > .local/deploy.log 2>&1; echo "exit=$?"; grep -E '^(==>|OK|WARNING|ERROR|FAILED)' .local/deploy.log
   ```
   On a non-zero exit, the last `==>` line names the failing step: read the log's tail for a
   preflight, sync or build failure, and `./infrastructure/droplet.sh logs` (secrets redacted) for a
   container that did not come up. Edit nothing while it syncs: it ships the tree as it is.
   It starts with a preflight (secrets in the git history and in the files to ship, then `grype`,
   which fails on High) and stops there on a finding; `SKIP_PREFLIGHT=1` is for an emergency only.
   A no-change deploy restarts nothing; a changed `uv.lock` or Dockerfile adds an on-droplet
   `docker compose build`. It waits for the bot and the Mini App, then checks the public Mini App
   URL when Funnel is on (a warning, not a failure: the first certificate can take minutes). A
   failed build stops before `up -d`, so the old containers keep running. If the on-droplet build
   OOMs or fails, use the buildx fallback in `infrastructure/README.md`.

3. **Verify** in one gated call:
   ```bash
   ./infrastructure/droplet.sh status 10m   # containers, healthz, errors since the deploy, jobs running, last log lines, disk
   ./infrastructure/ssh-gate.sh status      # expect: closed
   ```
   Expected: `deploy.sh` printed `OK: miniapp healthy and bot polling` (plus `OK: Mini App
   reachable` with Funnel on); status shows every container `Up`, healthz `{"status":"ok"}` and 0
   errors (tracebacks, ERROR lines, `notes disabled`). For regression checks that cost nothing
   (agent previews in the new image, `notes-smoke`), see `docs/verifying.md` §4; the real-chat
   check in Telegram Web is `docs/verifying.md` §5.

4. **Report** — state what was deployed (branch/diff summary), the verification
   results, and the Mini App URL (`BOT_MINIAPP_URL`): the owner opens it with the 📒 button in
   the bot chat.

## Rollback

[rollback.md](rollback.md): the fast `ai_agents:previous` rollback, going further back, and why the
data survives a deploy.
