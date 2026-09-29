# 02 — Deploy the skeleton to the droplet

**What to build:** One command puts the current code on the ai_agents droplet next to the existing bot: a container image, a hardened Compose stack with the bot and the web service sharing one sqlite volume, the web bound to the droplet's loopback, and a deploy script that uploads only the allow-listed secrets, builds on the droplet, starts both services and waits until they are healthy. The README explains running locally, deploying, and opening the web UI through an SSH tunnel.

**Blocked by:** 01 — Walking skeleton

**Status:** done (in maxi-notes, before the merge — ADR-015)

- [ ] `./infrastructure/deploy.sh` (IP from the argument or from the ai_agents Terraform output) ends with `OK` after the health endpoint answers and the bot logs `polling as @`
- [ ] `ssh -N -L 8082:127.0.0.1:8082 root@<ip>` then `http://localhost:8082/` shows the list; the port is not reachable from outside the droplet
- [ ] `docker stats --no-stream` on the droplet shows the maxi-notes bot under 300 MB and the web under 160 MB, and the ai_agents containers still running
- [x] The web container receives no secrets (only the database path and log level); the bot's env file is mode 0600
- [x] The Compose project is named `maxi-notes` and its volume does not collide with ai_agents' volume
- [ ] Redeploying after a code change keeps existing Items (the volume survives)
- [x] `.env.example` documents every configuration variable; README covers local run, tests, deploy, tunnel, logs and a sqlite backup command

## Comments

**2026-09-18 — infrastructure written and validated locally; the droplet run is pending the Owner.** Done here: `infrastructure/Dockerfile` (python:3.12-slim + uv, manifests-first layering, non-root uid 10001, `/data` pre-owned), `infrastructure/docker-compose.yml` (project `maxi-notes`, hardening anchor copied from ai_agents, bot 300 MB / web 160 MB caps, web published on `127.0.0.1:8082`, volume `maxi-notes_appdata`), `infrastructure/deploy.sh` (rsync → allow-listed `app.env` at 0600 → build on droplet → chown volume → `up -d` → wait for `/healthz` + `polling as @`), `.dockerignore`, `.env.example`, README. Verified locally: `bash -n deploy.sh`; `docker build` succeeds (image ≈750 MB, mostly lxml/trafilatura and the SDKs); `maxi-bot` inside the image exits 1 with the clear config error; `maxi-web` inside the image serves `/healthz` and `/`. **Pending, needs the Owner:** a bot token from @BotFather and the Owner id in `.env`, then the first `./infrastructure/deploy.sh` run against the shared droplet — the three unticked criteria are checked on that run.

**Review (independent, read-only):** nothing high. Fixed: `README.md` moved out of the manifests layer so a docs-only change no longer reinstalls every wheel on the 1-vCPU droplet; the documented backup now takes a consistent snapshot via sqlite's backup API instead of copying the raw main file out from under WAL; `.env.example` and the README config table now say which variables are local-only (compose pins `MAXI_DB_PATH`, `WEB_HOST`, `WEB_PORT`) and that the web container's `LOG_LEVEL` is fixed.
