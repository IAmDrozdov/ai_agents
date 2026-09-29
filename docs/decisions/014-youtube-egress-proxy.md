# ADR-014: Optional egress proxy for YouTube (`YTDLP_PROXY`, WARP sidecar)

Status: Accepted (2026-09-20). Resolves ADR-010 §5 ("revisit when a datacenter IP block actually occurs").

## Context

The block happened in production: YouTube answered `LOGIN_REQUIRED` ("Sign in to
confirm you're not a bot") to the droplet's IP. Measured on the droplet on
2026-09-20, same minutes, same code:

| Route | Metadata (player) | Caption bytes (timedtext) | Audio |
|---|---|---|---|
| Direct | blocked for most videos, stably the same ones | OK, ~1 in 10 answers 429 | blocked with metadata |
| Cloudflare WARP | OK | **429 every time** | OK |

Neither route works alone. Caption URLs are not bound to the requesting IP
(`ip=0.0.0.0`), so they can be fetched on a different route than the one that
produced them. Through the real `preview()` in the hardened container: 4/4 videos
via the split route (including a 64-minute lecture and an auto-captions-only
video) against 0/4 direct.

The sample is small (a handful of videos, one day, one WARP identity), and WARP
egress addresses are reported to get blocked over time too. This is a mitigation
that worked when measured, not a guarantee.

## Decision

1. `Settings.ytdlp_proxy` (`YTDLP_PROXY`) — a machine-specific host, so layer 1
   (ADR-004). Unset means direct, exactly as before. Any proxy URL yt-dlp accepts
   works; nothing in the code is WARP-specific.
2. Split routing in `providers/youtube.py`: metadata and audio go through the
   proxy; caption bytes go **direct first** with short 429 retries, then one
   attempt through the proxy. Direct-first is what the measurements support for
   WARP; the proxy fallback covers operators whose proxy is a residential one.
3. An optional `warp` compose service (profile `warp`): `wgcf` registers a free
   WARP identity once into the `warpdata` volume, `wireproxy` serves it as SOCKS5
   on the compose network only. Userspace WireGuard, so it runs under the same
   hardening as the other services (non-root, `cap_drop: ALL`, read-only rootfs).
   Binaries are pinned by version and sha256 from each release's `checksums.txt`.
4. **Off by default, and the operator accepts Cloudflare's terms explicitly.**
   The sidecar refuses to register without `WARP_ACCEPT_TOS=yes`, and
   `deploy.sh` only enables the profile when `.env` carries that line. Scripted
   registration of consumer WARP is a grey area of those terms; that choice
   belongs to whoever runs the deployment, not to this repo's defaults.

## Rejected

- **WARP for everything** — captions would 429 every time, and a failed caption
  fetch falls through to the paid STT path (or fails outright past ~65 minutes).
- **JS runtime (deno) + PO-token provider (bgutil)** — not tested here. yt-dlp's
  own docs describe both as fixing format/403 problems, and bgutil's README says
  a PO token "does not guarantee bypassing ... bot checks". Costs ~100 MB of
  image and a Node sidecar on a 1 GB droplet. Worth revisiting if formats start
  failing with 403.
- **Cookies file** — depends on the operator's personal Google account, with
  account-flagging risk from a datacenter IP; reports of the bot check persisting
  even with valid cookies.
- **Hosted transcript APIs / `youtube-transcript-api`** — the library hits the same
  IP block; hosted APIs need a signup and key per self-hoster and do not cover the
  audio fallback.
- **Forced IPv6** — the droplet has none, and it is host-provider-specific.

## Consequences

- A failed caption fetch still means paid STT, so the 429 retry is a cost guard.
  The backoff (2 s, 4 s) is a guess: no recoverable 429 was caught while measuring.
- yt-dlp failures are now logged with their raw message; before, the wrapped
  error was the only trace and diagnosing this needed a manual reproduction.
- `deploy.sh`'s allow-list gains `YTDLP_PROXY` (amends ADR-008's list).
- Turning WARP off later: remove both `.env` lines, redeploy, then on the host
  `docker compose -f /opt/ai_agents/src/infrastructure/docker/docker-compose.yml --profile warp rm -sf warp`.
- The sidecar sits on its own `egress` network with the bot only; the dashboard
  cannot reach the unauthenticated SOCKS5 listener.

## Revisit when

- WARP egress gets blocked too → re-register (`docker volume rm docker_warpdata`
  and redeploy) or point `YTDLP_PROXY` at another proxy.
- Direct caption fetches start failing consistently → captions need the proxy
  route, which WARP cannot serve; that is the point to evaluate a paid proxy.
