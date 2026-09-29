#!/usr/bin/env bash
# Deploy the repo to the droplet and (re)start its services.
# Usage: [SSH_KEY=~/.ssh/key] ./infrastructure/deploy.sh [droplet-ip]
# SSH_KEY is optional; unset means ssh-agent / ~/.ssh/config pick the identity.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_KEY="${SSH_KEY:-}"
IP="${1:-$(terraform -chdir="$REPO_ROOT/infrastructure/terraform" output -raw droplet_ipv4)}"
SSH_OPTS=(${SSH_KEY:+-i "$SSH_KEY"} -o StrictHostKeyChecking=accept-new)
COMPOSE="docker compose -f /opt/ai_agents/src/infrastructure/docker/docker-compose.yml"
APP_UID=10001

# Optional WARP egress sidecar (ADR-014): opt-in by accepting Cloudflare's terms in .env.
WARP_ACCEPT_TOS="$(grep -E '^WARP_ACCEPT_TOS=' "$REPO_ROOT/.env" | tail -n 1 | cut -d= -f2- || true)"
if [ "$WARP_ACCEPT_TOS" = "yes" ]; then
  COMPOSE="WARP_ACCEPT_TOS=yes $COMPOSE --profile warp"
elif grep -q -E '^YTDLP_PROXY=.*//warp[:/]' "$REPO_ROOT/.env"; then
  echo "ERROR: YTDLP_PROXY points at the warp sidecar, but WARP_ACCEPT_TOS=yes is not set in .env" >&2
  exit 1
fi

echo "==> syncing repo to root@$IP:/opt/ai_agents/src"
rsync -az --delete \
  -e "ssh ${SSH_OPTS[*]}" \
  --exclude .git --exclude .venv --exclude '.env*' --exclude '__pycache__' \
  --exclude .ruff_cache --exclude .ty_cache --exclude .local --exclude data \
  --exclude node_modules --exclude 'infrastructure/terraform/.terraform' \
  --exclude '*.tfstate*' --exclude 'infrastructure/terraform/terraform.tfvars' \
  --exclude .DS_Store --exclude dist --exclude .uv-cache \
  --exclude .claude --exclude .cursor --exclude .vscode \
  --exclude '*.sqlite3*' \
  "$REPO_ROOT/" "root@$IP:/opt/ai_agents/src/"

echo "==> uploading bot.env (allow-listed keys only)"
# Only the bot container needs secrets, plus the BOT_*/NOTES_* policy; DO_API_KEY etc. never leave this machine.
BOT_ENV="$(grep -E '^(OPENAI_API_KEY|TELEGRAM_BOT_TOKEN|ADMIN_TELEGRAM_ID|LOG_LEVEL|YTDLP_PROXY|BOT_[A-Z_]+|NOTES_[A-Z_]+)=' "$REPO_ROOT/.env" || true)"
for key in OPENAI_API_KEY TELEGRAM_BOT_TOKEN ADMIN_TELEGRAM_ID; do
  grep -q "^$key=." <<<"$BOT_ENV" || { echo "ERROR: $key is not set in .env" >&2; exit 1; }
done
printf '%s\n' "$BOT_ENV" \
  | ssh "${SSH_OPTS[@]}" "root@$IP" 'umask 077; cat > /opt/ai_agents/bot.env; rm -f /opt/ai_agents/.env'

echo "==> building and starting services"
# The containers run as uid $APP_UID, so the sqlite volume must belong to it. The
# chown is idempotent and only matters the first time after the non-root switch.
ssh "${SSH_OPTS[@]}" "root@$IP" "
  set -e
  $COMPOSE build --pull
  docker run --rm --user 0 -v docker_appdata:/data ai_agents:latest \
    chown -R $APP_UID:$APP_UID /data
  $COMPOSE up -d
  docker image prune -f
"

echo "==> waiting for the services to come up"
ssh "${SSH_OPTS[@]}" "root@$IP" "
  for i in \$(seq 1 30); do
    if curl -fsS http://127.0.0.1:8081/healthz >/dev/null 2>&1 \
       && $COMPOSE logs --since 5m bot 2>/dev/null | grep -q 'polling as @'; then
      echo 'OK: dashboard healthy and bot polling'
      exit 0
    fi
    sleep 2
  done
  echo 'FAILED: services did not come up in 60s' >&2
  $COMPOSE ps >&2
  $COMPOSE logs --tail 40 bot >&2
  exit 1
"
# Checked after the bot on purpose: a slow notes UI must not read as a failed bot deploy.
ssh "${SSH_OPTS[@]}" "root@$IP" "
  for i in \$(seq 1 30); do
    if curl -fsS http://127.0.0.1:8082/healthz >/dev/null 2>&1; then
      echo 'OK: notes web healthy'
      exit 0
    fi
    sleep 2
  done
  echo 'FAILED: notes-web did not come up in 60s (the bot is up)' >&2
  $COMPOSE logs --tail 40 notes-web >&2
  exit 1
"

echo "==> done"
echo "    logs:      ssh ${SSH_KEY:+-i $SSH_KEY} root@$IP '$COMPOSE logs -f bot'"
echo "    dashboard: ssh ${SSH_KEY:+-i $SSH_KEY} -N -L 8081:127.0.0.1:8081 root@$IP   ->   http://localhost:8081"
echo "    notes:     ssh ${SSH_KEY:+-i $SSH_KEY} -N -L 8082:127.0.0.1:8082 root@$IP   ->   http://localhost:8082"
