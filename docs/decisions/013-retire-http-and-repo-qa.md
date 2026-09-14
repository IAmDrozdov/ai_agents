# ADR-013: Retire the http/web interface and the repo_qa workflow

Status: Accepted (2026-09-12). Supersedes ADR-009; supersedes the HTTP/web-specific
context in ADR-005 and ADR-008 (their decisions stand).

## Decision

1. `interfaces/http` and `interfaces/web` are deleted. The Telegram bot is the only
   user-facing interface; `interfaces/smoke` is the terminal adapter (ADR-012).
2. `workflows/repo_qa` is deleted, together with `infrastructure/setup_repos.sh`,
   the `/repos` mount, `REPO_QA_ROOT`, `ANTHROPIC_API_KEY`, and the `ripgrep`/`git`/
   weasyprint system packages in the Docker image.

## Context

The owner uses this repo only as the Telegram bot. The http interface was last
touched on 2026-08-07, and only to add a `repo_qa` route; the bot dropped `repo_qa`
on 2026-09-01, and http never learned `yt_dub`. A dead adapter still had to pass
`ty` and the layer checker on every change and had already drifted twice (its own
config builder with different defaults, no price fields). `repo_qa` had no caller
left.

## Consequences

- No HTTP exposure, no web UI, no Anthropic dependency. Re-adding a second
  user-facing interface means a new thin adapter with a registry over the job
  contract, not a revival of the deleted code.
- The Docker image loses ~100 MB of system packages; the droplet no longer needs
  the repo cron.
