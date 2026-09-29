# infrastructure

Terraform + Docker deployment of the Telegram bot and usage dashboard to a
single DigitalOcean droplet.

## What runs where

- **Droplet** (`s-1vcpu-1gb`, ~$6/mo, Ubuntu 24.04 + 2 GB swap): Docker Compose
  with two containers built from one image —
  - `bot` — `telegram-bot`, long polling (outbound only, no public ingress)
  - `dashboard` — `usage-dashboard`, published on the droplet's **loopback only**
    (`127.0.0.1:8081`)
- **sqlite** lives on the named volume `appdata` (`/data/telegram_bot.sqlite3`);
  it survives rebuilds/redeploys and dies only with `docker volume rm` or
  `terraform destroy`.
- **Firewall**: inbound TCP/22 only; all egress open.
- **Containers**: non-root, `cap_drop: ALL`, read-only image with `/tmp` in RAM,
  `pids_limit`, memory caps (bot 700 MB, dashboard 160 MB) — a hostile document
  cannot take the host down, only its own container.
- **Host**: fail2ban (systemd backend), `PermitRootLogin prohibit-password`,
  unattended-upgrades incl. Docker's repo, auto-reboot 04:30 when a kernel lands.

## Configure (once)

Two values are yours to set:

- `infrastructure/terraform/terraform.tfvars` (gitignored) — copy
  `terraform.tfvars.example` and set `ssh_key_name`: the name of an SSH key already
  uploaded to your DigitalOcean account (`doctl compute ssh-key list`, or the control
  panel). Region, droplet size and name have defaults you can override there too.
- `SSH_KEY` (optional) — path to the matching private key, e.g.
  `export SSH_KEY=~/.ssh/id_ed25519`. Unset means ssh-agent / `~/.ssh/config` decide.
  Every command below uses `${SSH_KEY:+-i "$SSH_KEY"}`, so it works either way.

## Prerequisites

- `terraform` >= 1.5 (`brew install hashicorp/tap/terraform`)
- repo `.env` filled: `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `DO_API_KEY`
- budget: the default droplet is ~$6/mo, plus your OpenAI usage

## First-time provision

```bash
export TF_VAR_do_token="$(grep '^DO_API_KEY=' .env | cut -d= -f2)"
terraform -chdir=infrastructure/terraform init
terraform -chdir=infrastructure/terraform apply
# wait ~2-3 min for cloud-init (Docker install), then:
ssh ${SSH_KEY:+-i "$SSH_KEY"} root@$(terraform -chdir=infrastructure/terraform output -raw droplet_ipv4) docker version
```

`deploy.sh` trusts whatever host key answers on first connection
(`StrictHostKeyChecking=accept-new`) before it pipes `bot.env` over that same session —
fine for a single operator, but worth a moment: compare the fingerprint SSH prints on
that first connection against the one in the DigitalOcean console for this droplet.

## Deploy (first time and every update)

```bash
./infrastructure/deploy.sh
```

Rsyncs the repo to `/opt/ai_agents/src`, uploads **only** `OPENAI_API_KEY`,
`TELEGRAM_BOT_TOKEN`, `ADMIN_TELEGRAM_ID`, `LOG_LEVEL`, `YTDLP_PROXY` and the `BOT_*`
operator settings from `.env` as `/opt/ai_agents/bot.env` (0600; the dashboard container
gets no secrets at all), builds the image **on the droplet** (all deps ship manylinux
wheels; 1 GB RAM + swap is enough), and runs `docker compose up -d`. With
`WARP_ACCEPT_TOS=yes` in `.env` it also starts the optional `warp` egress sidecar
(ADR-014).

Before a deploy, scan the lockfile for known vulnerabilities:

```bash
grype dir:. --only-fixed
```

Fallback if an on-droplet build ever fails: build locally for amd64 and ship
the image without a registry:

```bash
docker buildx build --platform linux/amd64 -f infrastructure/docker/Dockerfile -t ai_agents:latest .
docker save ai_agents:latest | ssh ${SSH_KEY:+-i "$SSH_KEY"} root@<ip> docker load
```

## Dashboard access (SSH tunnel — no auth by design)

```bash
ssh ${SSH_KEY:+-i "$SSH_KEY"} -N -L 8081:127.0.0.1:8081 root@<droplet-ip>
# then open http://localhost:8081
```

## Operations

```bash
IP=$(terraform -chdir=infrastructure/terraform output -raw droplet_ipv4)
ssh ${SSH_KEY:+-i "$SSH_KEY"} root@$IP 'docker compose -f /opt/ai_agents/src/infrastructure/docker/docker-compose.yml logs -f bot'
# sqlite backup:
ssh ${SSH_KEY:+-i "$SSH_KEY"} root@$IP 'cat $(docker volume inspect -f "{{.Mountpoint}}" docker_appdata)/telegram_bot.sqlite3' > backup.sqlite3
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
- `DO_API_KEY` is read only here (as `TF_VAR_do_token`); `deploy.sh` never uploads
  it, so no container sees it.
- `cloud-init.yml` runs on first boot only and `main.tf` ignores later `user_data`
  drift, so editing it never forces a droplet replacement (which would drop the
  sqlite volume). Apply host changes by hand, or reprovision deliberately.
- Droplet size is a variable; `s-1vcpu-512mb-10gb` ($4/mo) works but leaves
  little RAM headroom for large PDFs.
- The dashboard port (8081) is fixed in `docker-compose.yml` and `deploy.sh`; change
  both if it collides with something on your host.
