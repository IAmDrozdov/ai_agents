#!/usr/bin/env bash
# Deploy the repo to the droplet and (re)start its services.
# Usage: [SSH_KEY=~/.ssh/key] [SKIP_PREFLIGHT=1] ./infrastructure/deploy.sh [droplet-ip]
# SSH_KEY is optional; unset means ssh-agent / ~/.ssh/config pick the identity.
# Needs DO_API_KEY in .env: the droplet's SSH port is opened for this run only (ssh-gate.sh).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SSH_KEY="${SSH_KEY:-}"
IP="${1:-$(terraform -chdir="$REPO_ROOT/infrastructure/terraform" output -raw droplet_ipv4)}"
SSH_OPTS=(${SSH_KEY:+-i "$SSH_KEY"} -o StrictHostKeyChecking=accept-new)
COMPOSE="docker compose -f /opt/ai_agents/src/infrastructure/docker/docker-compose.yml"
APP_UID=10001
RSYNC_EXCLUDES=(
  --exclude .git --exclude .venv --exclude '.env*' --exclude '__pycache__'
  --exclude .ruff_cache --exclude .ty_cache --exclude .local --exclude .scratch --exclude data
  --exclude node_modules --exclude 'infrastructure/terraform/.terraform'
  --exclude '*.tfstate*' --exclude 'infrastructure/terraform/terraform.tfvars'
  --exclude .DS_Store --exclude dist --exclude .uv-cache
  --exclude .claude --exclude .cursor --exclude .vscode
  --exclude '*.sqlite3*' --exclude CLAUDE.local.md
)

# rsync ships the working tree, not git, so the files to ship are scanned as well as the history.
preflight() {
  echo "==> preflight: secrets in git history and in the files to ship, vulnerable dependencies"
  command -v grype >/dev/null || { echo "ERROR: grype is not installed (brew install grype)" >&2; exit 1; }
  "$REPO_ROOT/tools/check_secrets.sh"
  local staging
  staging="$(mktemp -d)"
  rsync -a "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "$staging/"
  trufflehog filesystem "$staging" --no-verification --no-update --fail || { rm -rf "$staging"; exit 1; }
  rm -rf "$staging"
  (cd "$REPO_ROOT" && grype dir:. --only-fixed)
}

# SSH is closed by default (ADR-017): check first, then run the whole deploy inside the gate.
if [ -z "${SSH_GATE_HELD:-}" ]; then
  [ -n "${SKIP_PREFLIGHT:-}" ] || preflight
  exec "$REPO_ROOT/infrastructure/ssh-gate.sh" run "$0" "$@"
fi

# Optional WARP egress sidecar (ADR-014): opt-in by accepting Cloudflare's terms in .env.
WARP_ACCEPT_TOS="$(grep -E '^WARP_ACCEPT_TOS=' "$REPO_ROOT/.env" | tail -n 1 | cut -d= -f2- || true)"
if [ "$WARP_ACCEPT_TOS" = "yes" ]; then
  COMPOSE="WARP_ACCEPT_TOS=yes $COMPOSE --profile warp"
elif grep -q -E '^YTDLP_PROXY=.*//warp[:/]' "$REPO_ROOT/.env"; then
  echo "ERROR: YTDLP_PROXY points at the warp sidecar, but WARP_ACCEPT_TOS=yes is not set in .env" >&2
  exit 1
fi

# The value of a KEY=value line in .env (last one wins, surrounding quotes stripped); empty if unset.
env_value() {
  { grep -E "^$1=" "$REPO_ROOT/.env" || true; } | tail -n 1 | cut -d= -f2- | sed -E "s/^['\"]//; s/['\"]\$//"
}

# Optional Mini App ingress (ADR-016): the funnel sidecar publishes the miniapp service over HTTPS.
TS_AUTHKEY="$(env_value TS_AUTHKEY)"
MINIAPP_URL="$(env_value BOT_MINIAPP_URL)"
if [ -n "$MINIAPP_URL" ] && ! [[ "$MINIAPP_URL" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?/?$ ]]; then
  echo "ERROR: BOT_MINIAPP_URL must look like https://host (no path or query)" >&2
  exit 1
fi
if [ -n "$TS_AUTHKEY" ]; then
  COMPOSE="$COMPOSE --profile funnel"
  [ -n "$MINIAPP_URL" ] || echo "WARNING: TS_AUTHKEY is set but BOT_MINIAPP_URL is not: the bot will not offer the app" >&2
fi

echo "==> syncing repo to root@$IP:/opt/ai_agents/src"
rsync -az --delete \
  -e "ssh ${SSH_OPTS[*]}" \
  "${RSYNC_EXCLUDES[@]}" \
  "$REPO_ROOT/" "root@$IP:/opt/ai_agents/src/"

echo "==> uploading bot.env (allow-listed keys only)"
# Only the bot container needs secrets, plus the BOT_*/NOTES_* policy; DO_API_KEY etc. never leave this machine.
BOT_ENV="$(grep -E '^(OPENAI_API_KEY|TELEGRAM_BOT_TOKEN|ADMIN_TELEGRAM_ID|LOG_LEVEL|YTDLP_PROXY|BOT_[A-Z_]+|NOTES_[A-Z_]+)=' "$REPO_ROOT/.env" || true)"
for key in OPENAI_API_KEY TELEGRAM_BOT_TOKEN ADMIN_TELEGRAM_ID; do
  grep -q "^$key=." <<<"$BOT_ENV" || { echo "ERROR: $key is not set in .env" >&2; exit 1; }
done
printf '%s\n' "$BOT_ENV" \
  | ssh "${SSH_OPTS[@]}" "root@$IP" 'umask 077; cat > /opt/ai_agents/bot.env; rm -f /opt/ai_agents/.env'

echo "==> uploading miniapp.env and funnel.env"
# The public Mini App gets only a key derived from the bot token (it cannot act as the bot), and the
# Tailscale auth key goes to the funnel container alone (ADR-016).
MINIAPP_INIT_SECRET="$(printf %s "$(env_value TELEGRAM_BOT_TOKEN)" \
  | python3 -c 'import hashlib, hmac, sys; print(hmac.new(b"WebAppData", sys.stdin.buffer.read(), hashlib.sha256).hexdigest())')"
{ grep -E '^(ADMIN_TELEGRAM_ID|LOG_LEVEL)=' "$REPO_ROOT/.env" || true; printf 'MINIAPP_INIT_SECRET=%s\n' "$MINIAPP_INIT_SECRET"; } \
  | ssh "${SSH_OPTS[@]}" "root@$IP" 'umask 077; cat > /opt/ai_agents/miniapp.env'
printf 'TS_AUTHKEY=%s\n' "$TS_AUTHKEY" \
  | ssh "${SSH_OPTS[@]}" "root@$IP" 'umask 077; cat > /opt/ai_agents/funnel.env'

echo "==> building and starting services"
# The containers run as uid $APP_UID, so the sqlite volume must belong to it. The
# chown is idempotent and only matters the first time after the non-root switch.
# ai_agents:previous moves only when the layers changed (the image id changes on every build);
# the old image needs a tag of its own to survive the build.
ssh "${SSH_OPTS[@]}" "root@$IP" "
  set -e
  docker tag ai_agents:latest ai_agents:before-build 2>/dev/null || true
  $COMPOSE build --pull
  layers() { docker image inspect -f '{{json .RootFS.Layers}}' \"\$1\" 2>/dev/null || true; }
  if [ -n \"\$(layers ai_agents:before-build)\" ] \
     && [ \"\$(layers ai_agents:before-build)\" != \"\$(layers ai_agents:latest)\" ]; then
    docker tag ai_agents:before-build ai_agents:previous
  fi
  docker rmi ai_agents:before-build >/dev/null 2>&1 || true
  docker run --rm --user 0 -v docker_appdata:/data ai_agents:latest \
    chown -R $APP_UID:$APP_UID /data
  $COMPOSE up -d --remove-orphans
  docker image prune -f
  docker builder prune -f --filter until=24h
"

echo "==> waiting for the services to come up"
ssh "${SSH_OPTS[@]}" "root@$IP" "
  for i in \$(seq 1 30); do
    if curl -fsS http://127.0.0.1:8083/healthz >/dev/null 2>&1 \
       && $COMPOSE logs --since 5m bot 2>/dev/null | grep -q 'polling as @'; then
      echo 'OK: miniapp healthy and bot polling'
      exit 0
    fi
    sleep 2
  done
  echo 'FAILED: services did not come up in 60s' >&2
  $COMPOSE ps >&2
  $COMPOSE logs --tail 40 bot miniapp >&2
  exit 1
"
# Checked after the bot on purpose: a slow first Funnel certificate must not read as a failed bot deploy.
# It runs on the droplet, which is outside your tailnet, so it tests the public path even when
# this machine is a tailnet member (MagicDNS would answer here with a private address).
if [ -n "$TS_AUTHKEY" ] && [ -n "$MINIAPP_URL" ]; then
  echo "==> checking the public Mini App URL from the droplet"
  if ssh "${SSH_OPTS[@]}" "root@$IP" "
    for i in \$(seq 1 45); do
      curl -fsS '${MINIAPP_URL%/}/healthz' >/dev/null 2>&1 && exit 0
      sleep 2
    done
    exit 1
  "; then
    echo "OK: Mini App reachable at $MINIAPP_URL"
  else
    echo "WARNING: $MINIAPP_URL is not reachable yet (the first Funnel certificate can take minutes); the bot is up." >&2
    echo "         ./infrastructure/ssh-gate.sh ssh '$COMPOSE logs --tail 40 funnel'" >&2
  fi
fi

echo "==> done"
echo "    logs:     ./infrastructure/ssh-gate.sh ssh '$COMPOSE logs -f bot'"
if [ -n "$MINIAPP_URL" ]; then
  echo "    mini app: $MINIAPP_URL   (the 📒 button in the bot chat)"
fi
