#!/usr/bin/env bash
# Production inspection in one gated SSH call each (ADR-017); output stays short and secrets are redacted.
# Usage: [SSH_KEY=~/.ssh/key] droplet.sh status [since] | logs [service] [since] | sql <notes|bot> "<SELECT ...>" | py <file.py>
# status, logs and sql only read; py runs any Python inside the bot container.
set -euo pipefail

GATE="$(cd "$(dirname "$0")" && pwd)/ssh-gate.sh"
COMPOSE="docker compose -f /opt/maxi_bot/src/infrastructure/docker/docker-compose.yml"
# Telegram bot tokens, OpenAI keys, Tailscale auth keys and 64-hex secrets (HMAC keys, initData hashes).
REDACT="sed -E 's/[0-9]{8,10}:[A-Za-z0-9_-]{30,}/<TG_TOKEN>/g; s/sk-[A-Za-z0-9_-]{20,}/<OPENAI_KEY>/g; s/tskey-[A-Za-z0-9-]+/<TS_KEY>/g; s/[0-9a-f]{64}/<HEX64>/g'"

usage() {
  echo "usage: droplet.sh status [since=60m] | logs [service=bot] [since=15m] | sql <notes|bot> \"<SELECT ...>\" | py <file.py>" >&2
  exit 2
}

case "${1:-}" in
  status)
    since="${2:-60m}"
    [[ "$since" =~ ^[0-9]+[smh]$ ]] || usage
    # Exits non-zero when a core container is missing, healthz fails or the jobs query fails.
    "$GATE" ssh 'bash -s' <<REMOTE
set -u
fail=0
echo "== containers"
names="\$(docker ps --format '{{.Names}}: {{.Status}}')"
echo "\$names"
for c in docker-bot-1 docker-miniapp-1; do
  grep -q "^\$c: Up" <<<"\$names" || { echo "MISSING or not Up: \$c"; fail=1; }
done
printf '== miniapp healthz: '
curl -fsS -m 5 http://127.0.0.1:8083/healthz || { echo FAILED; fail=1; }
echo
printf '== errors in the last $since: '
for s in bot miniapp; do
  printf '%s %s  ' "\$s" "\$($COMPOSE logs --since $since \$s 2>&1 | grep -cE 'Traceback|ERROR|CRITICAL|notes disabled')"
done
echo
printf '== jobs running: '
docker exec docker-bot-1 python -c "import sqlite3; c = sqlite3.connect('file:/data/telegram_bot.sqlite3?mode=ro', uri=True); print(c.execute(\"SELECT count(*) FROM jobs WHERE status='running'\").fetchone()[0])" </dev/null 2>/dev/null \
  || { echo "UNKNOWN (query failed)"; fail=1; }
echo "== bot log, last 5 lines"
$COMPOSE logs --tail 5 --no-log-prefix bot 2>&1 | $REDACT | cut -c1-200
printf '== disk /: '; df -h / | awk 'NR==2 {print \$5" used, "\$4" free"}'
printf '== memory: '; free -m | awk '/^Mem:/ {print \$7" MB available of "\$2}'
exit \$fail
REMOTE
    ;;
  logs)
    service="${2:-bot}"
    since="${3:-15m}"
    [[ "$service" =~ ^[a-z]+$ && "$since" =~ ^[0-9]+[smh]$ ]] || usage
    "$GATE" ssh "$COMPOSE logs --since $since --no-log-prefix $service 2>&1 | $REDACT | cut -c1-300 | tail -n 60"
    ;;
  sql)
    [ $# -eq 3 ] || usage
    case "$2" in
      notes) db=/data/notes.sqlite3 ;;
      bot) db=/data/telegram_bot.sqlite3 ;;
      *) usage ;;
    esac
    # The query travels on stdin, so no shell quoting on either side can break it. mode=ro alone
    # still lets VACUUM INTO and ATTACH write files, so an authorizer allows only reads.
    printf '%s' "$3" | "$GATE" ssh "docker exec -i docker-bot-1 python -c \"
import sqlite3, sys
OK = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, 33}
con = sqlite3.connect('file:$db?mode=ro', uri=True)
con.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in OK else sqlite3.SQLITE_DENY)
cur = con.execute(sys.stdin.read())
print('\t'.join(d[0] for d in cur.description or []))
rows = cur.fetchmany(201)
for row in rows[:200]:
    print('\t'.join('' if v is None else str(v)[:200] for v in row))
if len(rows) > 200:
    print('... more than 200 rows, add a LIMIT')
\" 2>&1 | $REDACT"
    ;;
  py)
    [ $# -eq 2 ] && [ -f "$2" ] || usage
    "$GATE" ssh "docker exec -i docker-bot-1 python - 2>&1 | $REDACT | tail -n 80" < "$2"
    ;;
  *) usage ;;
esac
