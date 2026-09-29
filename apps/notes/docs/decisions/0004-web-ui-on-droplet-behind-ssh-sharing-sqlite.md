# The web UI runs on the droplet behind SSH and shares sqlite with the bot

_Amended by ai_agents ADR-015 (2026-09-29): the web is the `notes-web` service in the ai_agents compose stack, and the "separate stack" and "never touched from this repo" parts no longer apply._

_Superseded by ai_agents ADR-016 (2026-09-29): a Telegram Mini App replaces the SSH-tunnel web UI, and public HTTPS ingress (Tailscale Funnel, outbound only) is now used. The rest of this record is history._

The web UI is a second process in the same Docker Compose stack as the bot, on the DigitalOcean
droplet that already runs `ai_agents`, bound to `127.0.0.1:8082` with no authentication and
reached over an SSH tunnel; both processes read and write one sqlite file (WAL mode) on a named
volume. The droplet's firewall admits inbound TCP/22 only, and that stays true.

## Considered Options

- A site on the Owner's laptop connecting to a "cloud" database — rejected: the DB would have to be network-reachable, which means Postgres instead of sqlite plus either an exposed port or the very same SSH tunnel with more moving parts.
- A Telegram Mini App served by the bot — rejected for v1: needs public HTTPS ingress (firewall 443, a domain, TLS termination) and gives up the zero-public-ingress posture. It is the named v2 candidate if phone-side sorting proves necessary; the bot's Browse covers reading on the phone.

## Consequences

- No auth surface exists on the web UI by design; `TrustedHostMiddleware` guards against DNS rebinding through the open tunnel.
- Memory on the 1 GB droplet is shared with `ai_agents` (bot capped at 700 MB): maxi-notes caps `bot` at 300 MB and `web` at 160 MB; the escape hatch is a bigger droplet, not removing caps.
- Terraform and the firewall live in `ai_agents` and are never modified from this repo.
