#!/usr/bin/env bash
# SSH to the droplet is closed by default (ADR-017); this opens port 22 for this machine's address.
# Usage: [SSH_KEY=~/.ssh/key] ssh-gate.sh ssh [remote command] | run <command...> | open | close | status
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TF=(terraform -chdir="$REPO_ROOT/infrastructure/terraform")
API="https://api.digitalocean.com/v2"
HOLD_DIR="$REPO_ROOT/.local/ssh-gate"
SSH_KEY="${SSH_KEY:-}"

TOKEN="$({ grep -E '^DO_API_KEY=' "$REPO_ROOT/.env" || true; } | tail -n 1 | cut -d= -f2- | sed -E "s/^['\"]//; s/['\"]\$//")"
[ -n "$TOKEN" ] || { echo "ERROR: DO_API_KEY is not set in .env" >&2; exit 1; }
# Everything before the gated command reads /dev/null, so piped input reaches that command intact.
FIREWALL_ID="$("${TF[@]}" output -raw firewall_id </dev/null)"
IP="$("${TF[@]}" output -raw droplet_ipv4 </dev/null)"

# The token goes in through a file descriptor so it never shows in the process list.
api() {
  curl -fsS -X "$1" -H @<(printf 'Authorization: Bearer %s' "$TOKEN") \
    -H 'Content-Type: application/json' ${3:+-d "$3"} "$API$2" </dev/null
}

my_ip() {
  local ip
  ip="$(curl -4fsS --max-time 10 https://checkip.amazonaws.com </dev/null \
    || curl -4fsS --max-time 10 https://api.ipify.org </dev/null)"
  ip="${ip//[[:space:]]/}"
  [[ "$ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || { echo "ERROR: could not find this machine's public IPv4" >&2; exit 1; }
  printf %s "$ip"
}

# Every tcp/22 inbound rule on the firewall as one request body; empty when closed.
ssh_rules() {
  api GET "/firewalls/$FIREWALL_ID" | python3 -c '
import json, sys
rules = [r for r in json.load(sys.stdin)["firewall"]["inbound_rules"] if r["protocol"] == "tcp" and r["ports"] == "22"]
if rules: print(json.dumps({"inbound_rules": rules}))'
}

gate_open() {
  local ip
  ip="$(my_ip)"
  api POST "/firewalls/$FIREWALL_ID/rules" \
    "{\"inbound_rules\":[{\"protocol\":\"tcp\",\"ports\":\"22\",\"sources\":{\"addresses\":[\"$ip/32\"]}}]}" >/dev/null
  echo "ssh-gate: port 22 open for $ip" >&2
  # A dropped SYN hangs for the OS default (75 s on macOS), so the probe sets its own timeout.
  for _ in $(seq 1 30); do
    python3 -c 'import socket, sys; socket.create_connection((sys.argv[1], 22), timeout=2).close()' \
      "$IP" </dev/null 2>/dev/null && return 0
    sleep 1
  done
  echo "ERROR: port 22 did not open within 30s" >&2
  return 1
}

gate_close() {
  local body
  body="$(ssh_rules)"
  [ -z "$body" ] || api DELETE "/firewalls/$FIREWALL_ID/rules" "$body" >/dev/null
  echo "ssh-gate: port 22 closed" >&2
}

# Close only when no other gate process is alive, so a parallel session is not cut off.
release() {
  rm -f "$HOLD_DIR/$$"
  local f
  for f in "$HOLD_DIR"/*; do
    [ -e "$f" ] || continue
    kill -0 "$(basename "$f")" 2>/dev/null && return 0
    rm -f "$f"
  done
  gate_close
}

held() {
  mkdir -p "$HOLD_DIR"
  : > "$HOLD_DIR/$$"
  trap release EXIT
  trap 'exit 130' INT TERM
  gate_open
  SSH_GATE_HELD=1 "$@"
}

case "${1:-}" in
  ssh)
    shift
    held ssh ${SSH_KEY:+-i "$SSH_KEY"} -o StrictHostKeyChecking=accept-new "root@$IP" "$@"
    ;;
  run)
    shift
    [ $# -gt 0 ] || { echo "usage: ssh-gate.sh run <command...>" >&2; exit 2; }
    held "$@"
    ;;
  open) gate_open ;;
  close) gate_close ;;
  status)
    body="$(ssh_rules)"
    if [ -n "$body" ]; then echo "OPEN: $body"; else echo "closed"; fi
    ;;
  *)
    echo "usage: ssh-gate.sh ssh [remote command] | run <command...> | open | close | status" >&2
    exit 2
    ;;
esac
