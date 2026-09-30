# infrastructure

Terraform + Docker deployment of the Telegram bot and the admin Mini App to a
single DigitalOcean droplet.

## What runs where

- **Droplet** (`s-1vcpu-1gb`, ~$6/mo, Ubuntu 24.04 + 2 GB swap): Docker Compose
  with two containers built from one image, plus optional sidecars —
  - `bot` — `telegram-bot`, long polling (outbound only, no public ingress); also
    runs notes Capture and link enrichment for the admin (ADR-015)
  - `miniapp` — `telegram-miniapp`, the admin Mini App (ADR-016): every API call needs
    Telegram-signed data from the admin. Published on the droplet's loopback
    (`127.0.0.1:8083`) for the health check only
  - `funnel` (optional) — the Tailscale Funnel sidecar that publishes `miniapp` over HTTPS
    through an outbound tunnel
  - `warp` (optional) — the YouTube egress sidecar (ADR-014)
- **sqlite** lives on the named volume `appdata` (`/data/telegram_bot.sqlite3`,
  `/data/notes.sqlite3`);
  it survives rebuilds/redeploys and dies only with `docker volume rm` or
  `terraform destroy`.
- **Firewall**: no inbound rule at all; all egress open. SSH is opened for your current address
  only while `ssh-gate.sh` runs a command (ADR-017). The Mini App needs no inbound rule, because
  Funnel is an outbound tunnel.
- **Containers**: non-root, `cap_drop: ALL`, read-only image with `/tmp` in RAM,
  `pids_limit`, memory caps (bot 700 MB, miniapp 160 MB, funnel 96 MB) — a hostile document
  cannot take the host down, only its own container.
- **Host**: fail2ban (systemd backend), key-only root login with forwarding limited to local,
  unattended-upgrades incl. Docker's repo, auto-reboot 04:30 when a kernel lands, journal capped
  at 100 MB, and multipathd, ModemManager, udisks2 and fwupd switched off.

## Configure (once)

Two values are yours to set:

- `infrastructure/terraform/terraform.tfvars` (gitignored) — copy
  `terraform.tfvars.example` and set `ssh_key_name`: the name of an SSH key already
  uploaded to your DigitalOcean account (`doctl compute ssh-key list`, or the control
  panel). Region, droplet size and name have defaults you can override there too.
- `SSH_KEY` (optional) — path to the matching private key, e.g.
  `export SSH_KEY=~/.ssh/id_ed25519`. Unset means ssh-agent / `~/.ssh/config` decide.
  `deploy.sh` and `ssh-gate.sh` both read it.

## Prerequisites

- `terraform` >= 1.5 (`brew install hashicorp/tap/terraform`)
- `trufflehog` and `grype` (`brew install trufflehog grype`): the deploy preflight
- repo `.env` filled: `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `DO_API_KEY`
- budget: the default droplet is ~$6/mo, plus your OpenAI usage

## Reaching the droplet

Port 22 is closed. Every SSH command goes through the gate, which opens the port for your
current public address, runs the command and closes the port again:

```bash
./infrastructure/ssh-gate.sh ssh                      # interactive shell
./infrastructure/ssh-gate.sh ssh 'docker ps'          # one remote command
./infrastructure/ssh-gate.sh run scp root@<ip>:/root/x ./x   # anything else that needs the port
./infrastructure/ssh-gate.sh status                   # "closed", or the rule that is open
```

Locked out (the gate fails, or the address-echo service is down): `ssh-gate.sh open` leaves the
port open for your address until `ssh-gate.sh close`; `terraform apply -var
'ssh_allowed_cidrs=["<your-ip>/32"]'` opens it statically; the firewall page in the DigitalOcean
control panel does the same by hand. `close` removes every port-22 rule, a static one included.

## First-time provision

```bash
export TF_VAR_do_token="$(grep '^DO_API_KEY=' .env | cut -d= -f2)"
terraform -chdir=infrastructure/terraform init
terraform -chdir=infrastructure/terraform apply
# wait ~2-3 min for cloud-init (Docker install), then:
./infrastructure/ssh-gate.sh ssh docker version
```

`deploy.sh` trusts whatever host key answers on first connection
(`StrictHostKeyChecking=accept-new`) before it pipes `bot.env` over that same session —
fine for a single operator, but worth a moment: compare the fingerprint SSH prints on
that first connection against the one in the DigitalOcean console for this droplet.

## Deploy (first time and every update)

```bash
./infrastructure/deploy.sh
```

First a preflight, before the SSH port opens: trufflehog over the git history, the staged files
and exactly the files rsync would ship, then `grype dir:. --only-fixed`, which fails on High. A
finding stops the deploy; `SKIP_PREFLIGHT=1` skips the preflight for an emergency redeploy. The
rest runs inside the SSH gate.

Rsyncs the repo to `/opt/ai_agents/src`, uploads **only** `OPENAI_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `LOG_LEVEL`, `YTDLP_PROXY` and the `BOT_*`/`NOTES_*`
operator settings from `.env` as `/opt/ai_agents/bot.env` (0600). The Mini App container gets its
own `miniapp.env`: `ADMIN_TELEGRAM_ID`, `LOG_LEVEL` and `MINIAPP_INIT_SECRET`, a key derived from
the bot token on your machine (so `python3` must be on your PATH); the token itself never reaches
it. The Funnel sidecar gets `funnel.env` with `TS_AUTHKEY` only. It builds the image **on the
droplet** (all deps ship manylinux wheels; 1 GB RAM + swap is enough), and runs
`docker compose up -d --remove-orphans`. With `WARP_ACCEPT_TOS=yes` in `.env` it also starts the
optional `warp` egress sidecar (ADR-014), and with `TS_AUTHKEY` set the `funnel` sidecar (ADR-016).

A deploy that changes the image tags the one that was running as `ai_agents:previous`; a re-run
with no changes leaves `previous` alone and restarts nothing (a leftover `ai_agents:before-build`
tag is then normal: it names the image the running containers still use). Build cache older than
a day is dropped. To roll back without rebuilding:

```bash
./infrastructure/ssh-gate.sh ssh 'docker tag ai_agents:previous ai_agents:latest && docker compose -f /opt/ai_agents/src/infrastructure/docker/docker-compose.yml up -d'
```

Fallback if an on-droplet build ever fails: build locally for amd64 and ship
the image without a registry:

```bash
docker buildx build --platform linux/amd64 -f infrastructure/docker/Dockerfile -t ai_agents:latest .
docker save ai_agents:latest | ./infrastructure/ssh-gate.sh ssh docker load
```

## Mini App (Tailscale Funnel)

The admin Mini App is published by the `funnel` sidecar at `https://ai-agents.<tailnet>.ts.net`.
One-time setup (yours; it needs a Tailscale account):

1. Create a free Tailscale account. In the admin console under **DNS**, turn on MagicDNS and
   **HTTPS Certificates**, and note the tailnet name (`tailXXXX.ts.net`).
2. Under **Access controls**, the policy file must grant Funnel. Add
   `{"target": ["autogroup:member"], "attr": ["funnel"]}` to `nodeAttrs` if it is missing.
3. Under **Settings → Keys**, generate an auth key: not ephemeral, pre-approved.
4. In `.env` set `TS_AUTHKEY=tskey-auth-…` and `BOT_MINIAPP_URL=https://ai-agents.<tailnet>.ts.net`,
   then deploy.
5. After the first deploy, open **Machines → ai-agents → Disable key expiry**. Otherwise the node
   drops off after about 180 days and the app stops loading.

The node's identity lives in the `tsstate` volume; `terraform destroy` deletes it and a new auth
key is then needed. If a machine named `ai-agents` already exists in the tailnet, the new node
becomes `ai-agents-1` and the URL no longer matches: delete the old machine in the console.

If your own computer is on the tailnet, Chrome on it cannot show the app inside Telegram Web (the
name resolves to a private tailnet address, which Chrome refuses for a public page's frame). Phones
and Telegram Desktop are unaffected, so nothing needs changing (see `docs/verifying.md` §5 to test).

Check: `curl -fsS $BOT_MINIAPP_URL/healthz` answers, and `/api/usage` without Telegram data is 401.
Run it on the droplet (or any machine outside your tailnet): a tailnet member's MagicDNS answers with
a private address, which would pass even if Funnel were off. `deploy.sh` checks from the droplet.
Without Funnel the app is still on the droplet's loopback, for debugging:

```bash
IP=$(terraform -chdir=infrastructure/terraform output -raw droplet_ipv4)
./infrastructure/ssh-gate.sh run ssh ${SSH_KEY:+-i "$SSH_KEY"} -N -L 8083:127.0.0.1:8083 root@$IP   # http://localhost:8083
```

It only shows "open from Telegram" there: the API accepts nothing but signed initData
(`docs/verifying.md` §2).

## Operations

```bash
G=./infrastructure/ssh-gate.sh
IP=$(terraform -chdir=infrastructure/terraform output -raw droplet_ipv4)
$G ssh 'docker compose -f /opt/ai_agents/src/infrastructure/docker/docker-compose.yml logs -f bot'
# sqlite backup:
$G ssh 'cat $(docker volume inspect -f "{{.Mountpoint}}" docker_appdata)/telegram_bot.sqlite3' > backup.sqlite3
# notes run in WAL mode with two writers, so take a consistent snapshot instead of copying the file:
# (from the volume on the host: `docker cp` cannot read a container's tmpfs /tmp)
$G ssh 'V=$(docker volume inspect -f "{{.Mountpoint}}" docker_appdata); python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" $V/notes.sqlite3 /root/notes-backup.sqlite3'
$G run scp ${SSH_KEY:+-i "$SSH_KEY"} root@$IP:/root/notes-backup.sqlite3 ./notes-backup.sqlite3
$G ssh 'rm /root/notes-backup.sqlite3'   # do not leave copies of the data in /root
```

## Teardown

```bash
terraform -chdir=infrastructure/terraform destroy   # deletes droplet AND the sqlite volume
```

## Notes / tradeoffs

- Terraform state is **local** (`infrastructure/terraform/terraform.tfstate`,
  gitignored). Single-operator setup; if state is lost, the droplet is still
  visible in the DO console for manual import or deletion.
  `.terraform.lock.hcl` is committed.
- `DO_API_KEY` is read only on your machine, by Terraform (as `TF_VAR_do_token`) and by
  `ssh-gate.sh`; `deploy.sh` never uploads it, so no container sees it. It can be a custom-scope
  token: day to day the gate and `terraform plan` need only `droplet:read`, `firewall:read`,
  `firewall:update` and `ssh_key:read`.
- `cloud-init.yml` runs on first boot only and `main.tf` ignores later `user_data`
  drift, so editing it never forces a droplet replacement (which would drop the
  sqlite volume). Apply host changes by hand, or reprovision deliberately.
- Droplet size is a variable; `s-1vcpu-512mb-10gb` ($4/mo) works but leaves
  little RAM headroom for large PDFs.
- The Mini App port (8083) is fixed in `docker-compose.yml`, `deploy.sh` and `tailscale/serve.json`;
  change all three if it collides with something on your host.
