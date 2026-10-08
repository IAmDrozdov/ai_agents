# AGENTS.md

Map. Follow links. No rule duplication here. Humans start at `README.md`.

## What this is
Monorepo of local AI workflows exposed through one job contract (`shared.job`, ADR-012) by a private Telegram bot and a terminal smoke runner, plus one stateful app — `apps/notes`, the admin's save-for-later store (ADR-015). New interfaces are thin adapters holding a registry of workflow descriptors. No automated tests (ADR-001).

## Docs, read by task
- Any bot, notes or deploy work: `docs/runtime.md` first (what runs, how the parts talk, in-memory state, touch points).
- Layers, deps, interface exposure: `docs/architecture.md`. Naming, layout, configs, business docs: `docs/conventions.md`.
- uv, ruff, ty, pre-commit, layer checker, grype: `docs/tooling.md`. Approach -> skill -> binding rules: `docs/approaches-skills-rules-map.md`.
- Proving a change works with no tests (smoke, the offline bot harness, free production checks): `docs/verifying.md`.
- ADRs in `docs/decisions/` are binding: read every ADR that touches the area you change (a superseded one says so in its Status line). ADR-001 (no automated tests) and ADR-017 (SSH closed by default) apply everywhere.

## Common tasks
- New workflow -> `.skills/create-workflow.md`
- New node -> `.skills/create-node.md`
- Run a workflow from the terminal -> `uv run smoke <id> <path-or-url>`
- Notes (app) -> `apps/notes/README.md`; smoke: `uv run notes-smoke <url-or-text>`
- Admin Mini App (notes + usage) -> `docs/decisions/016-telegram-mini-app.md`, `docs/decisions/019-mini-app-over-a-slow-link.md` (caching, snapshot, polling), `docs/runtime.md`; checks: `docs/verifying.md` §2 and §5
- Domain terms -> `CONTEXT.md`
- New ADR -> `docs/decisions/NNN-title.md`
- Deploy bot to droplet -> `.claude/skills/deploy-bot/SKILL.md` (slash: `/deploy-bot`)
- Inspect production (status, logs, read-only SQL; `py` runs a probe script) -> `infrastructure/droplet.sh` (through the SSH gate)
- Backup / restore -> `infrastructure/README.md` "Backups", `docs/decisions/018-daily-backup-pulled-to-the-owners-mac.md`
- Change the bot's routing, cards or buttons -> `docs/runtime.md` (routing table, card lifecycle), then `docs/verifying.md` §3
- Live test in the real chat (last rung, owner-approved script) -> `.claude/skills/live-test/SKILL.md` (slash: `/live-test`)
- Add an env var or a service -> `docs/runtime.md` "Touch points"

## Hard layer rules (enforced by `tools/check_layers.py` + pre-commit)
- `interfaces/*` MAY import: `shared.*`, `workflows.<any>`, apps (`notes`).
- `interfaces/*` MUST NOT import: `langchain`, `langchain_core`, `langchain_community`, `langgraph`, `openai`, `anthropic`.
- `shared/*` MUST NOT import: `workflows.*`, `interfaces.*`.
- `workflows/<a>/*` MUST NOT import: `workflows/<b>/*`.
- `workflows/*` MUST NOT import: `interfaces/*`, apps.
- `shared/*` MUST NOT import: apps.
- `apps/*` MUST NOT import: `workflows.*`, `interfaces.*`, another app, `aiogram`/`fastapi`/`starlette`/`uvicorn`.

## Pre-commit
Hooks on `git commit`: ruff (`--fix` + format), ty (staged python), check_layers (full repo),
check_secrets (trufflehog over history + staged files; also runs on `git push`).
Manual run: `uv run pre-commit run --all-files`.

## Stop and ask
- Adding dependency to `shared/`
- Touching auth, secrets, env loading
- Cross-workflow refactor
- New top-level folder
- Breaking layer rules
- Adding tests (ADR-001)
- Reaching for LangGraph without ADR-003 justification
- Disabling pre-commit hooks

## Stack (fixed)
Py 3.12+, uv workspaces, Ruff, ty, Pydantic, LangChain (primary), LangGraph (justified), aiogram Telegram bot + FastAPI admin Mini App (notes and usage), sqlite, pre-commit.

## Agent skills

### Issue tracker
Local markdown under `.scratch/<feature>/` (gitignored). See `docs/agents/issue-tracker.md`.

### Triage labels
Five default roles (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs
Single-context root `CONTEXT.md` + `apps/notes/CONTEXT.md`; ADRs in `docs/decisions/`. See `docs/agents/domain.md`.

## Workflows index
`docs/workflows-index.md` (regen by create-workflow skill).
