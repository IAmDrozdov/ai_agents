# ADR-019: The Mini App is built for a slow link: few round trips, cached assets, a snapshot on the phone

Status: Accepted (2026-10-07). Amends ADR-016 (decision 2: how the shell is served). Amended by ADR-021 (the phone also keeps the navigation memory).

## Context

After the 2026-10-07 deploys the owner found the Mini App slow and heavy. Measured that day:

- **The server is not the cost.** Every API call computes in 0.1–1.7 ms. On the droplet,
  `127.0.0.1:8083` answers in 5–7 ms. CPU is 1–3% and load is 0.
- **The link is the cost.** Tailscale Funnel adds 250–450 ms to every request and 0.5–3 s to every
  new TLS connection, because TLS ends in tailscaled on the droplet. The funnel container was
  healthy, and netcheck found a DERP 17 ms away.
- **The app multiplied that cost.**
  - A launch was 6 sequential round trips: TLS, HTML, app.js, 5 modules, 2 more modules, then the API.
  - Every file was revalidated on every launch (`no-cache`), so each 304 still cost a round trip.
  - Nothing was compressed.
  - The notes tab needed 2 more sequential calls.
  - A pending Item re-downloaded every open list every 3 s.
- **Most of the megabytes were third-party covers** at full size (notes ADR-0012).

## Decision

1. **Assets.** Assets are served under `/static/<build>/…` with
   `public, max-age=31536000, immutable`. `<build>` is a hash of `miniapp/static`, computed at
   startup. The shell (`/`) is still revalidated (`no-cache`, ETag = a hash of the rendered shell), so a deploy reaches the
   webview on the next launch. The shell lists every module as `modulepreload`, so all of them
   load in one round trip. There is still no build step. Any build segment serves the current
   files, so a shell left open across a deploy still loads.
2. **gzip** for everything over 500 bytes. It sits inside the header middleware, which streams every response.
3. **A snapshot on the phone.** The last answers are kept in `Telegram.WebApp.DeviceStorage`
   (Bot API 9.0+), or in `localStorage` when the client is older or answers DeviceStorage with an error. Telegram Web answers `UNSUPPORTED`. They hold the Dashboard, the Sections,
   «Просрочено» and the first page of each Section viewed. A view paints from the snapshot at once,
   then revalidates in the background. A 401 or 403 wipes it.
4. **Fewer, parallel calls.** The notes tab loads the counts, «Просрочено» and the open Sections in
   one round of parallel calls. A pending Item is asked about alone (`/api/notes/items?ids=`). The
   pauses grow 3 s, 5 s, 10 s, 20 s, then 30 s, or last until its scheduled retry. List and item JSON
   share one compact shape, without bookkeeping fields and with five fields per Section.
5. **No cache on the server.** No Redis, Valkey or in-process cache. They would save about 1 ms
   against seconds of network.

## Considered Options

- **Redis or Valkey on the droplet.** Rejected. It would fit (300 MB free), but it caches on the wrong side of the slow link. It would also add a container, a backup and an attack surface.
- **A bundler or build step.** Rejected. `modulepreload` gives the same single round trip without breaking ADR-016's "no build step".
- **`stale-while-revalidate` on the shell.** Deferred. It could take TLS off the first paint. It is unproven for Telegram's iOS webview, and the first launch after a deploy would run the old build.
- **A faster ingress** (a direct WireGuard path, Cloudflare Tunnel, or Caddy on 443). Out of scope: the owner decides, and 017 or 016 would be amended.

## Consequences

- A warm launch makes one round trip for the shell and then paints. Measured locally on Chrome's
  "Fast 3G" (≈560 ms per request): first paint at 0.63 s; the old waterfall needed 5 round trips.
  A deploy makes the next launch download the assets once.
- The phone keeps up to about 1 MB of the owner's Items between launches, as Telegram's own cache does.
- The TLS setup through Funnel stays on every new connection. Only an ingress change removes it.
- The local Mini App computes its build at startup: restart it after editing a static file.
