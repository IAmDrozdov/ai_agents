# Instagram Enrichment uses Instagram's own anonymous embed surface — never the Owner's account

Instagram Links are enriched from the official **captioned embed page**
(`instagram.com/<reel|p|tv>/<code>/embed/captioned/`), the same document Instagram's `embed.js`
loads for any website, so it renders without a login: it carries the author, the caption and the
thumbnail. Meta's tokenless `instagram_oembed` endpoint (tokenless since 2026-06-15) was measured
to return only the bare embed markup — no author, caption or thumbnail without an app token — so
it is not used. Content from private accounts yields nothing there and degrades to the Owner's
Annotation plus the domain. Logging in as the Owner to get further — session cookies,
instaloader, yt-dlp with cookies — is forbidden from every host, not just the droplet.

## Considered Options

- Tokenless `instagram_oembed` — rejected after measuring it (2026-09-18): `fields=` needs an app id, and the default answer has no metadata.
- The reel page's `og:` tags — works from a residential IP, but the page itself is what Instagram login-walls for datacenter visitors; kept as a possible fallback, not the primary route.
- Session-cookie scraping as the Owner — rejected: Instagram blacklists datacenter IP ranges (DigitalOcean included), the documented failure mode is a `challenge_required` loop on the Owner's personal account, and sessions expire within hours.
- A Meta app with a token — unnecessary at single-owner volume; it remains the escape hatch if the embed page ever stops rendering anonymously.

## Consequences

- A share of reels (private accounts) will show only the Annotation and "instagram"; this is expected, not a bug.
- If private content ever matters, the only acceptable shape is a fetch from a residential IP (the Owner's laptop), and it is out of scope for v1.
