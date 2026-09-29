# AGENTS.md

Map. Follow links. No rule duplication here. Humans start at `README.md`.

## What this is
Monorepo of local AI workflows exposed through one job contract (`shared.job`, ADR-012) by a private Telegram bot and a terminal smoke runner, plus one stateful app — `apps/notes`, the admin's save-for-later store (ADR-015). New interfaces are thin adapters holding a registry of workflow descriptors. No automated tests (ADR-001).

## Read first
1. `docs/runtime.md` — what runs, what each part does, how they talk, in-memory state, touch points; before any bot, notes or deploy work
2. `docs/architecture.md` — layers, deps, interface exposure flow
3. `docs/conventions.md` — naming, layout, configs, business-doc conventions
4. `docs/decisions/` — ADRs. Read all.
5. `docs/tooling.md` — uv, ruff, ty, pre-commit, layer checker, grype
6. `docs/approaches-skills-rules-map.md` — approach -> skill -> binding rules
7. `docs/verifying.md` — how to prove a change works with no tests: smoke, the offline bot harness, free production checks

## Common tasks
- New workflow -> `.skills/create-workflow.md`
- New node -> `.skills/create-node.md`
- Run a workflow from the terminal -> `uv run smoke <id> <path-or-url>`
- Notes (app) -> `apps/notes/README.md`; smoke: `uv run notes-smoke <url-or-text>`
- Admin Mini App (notes + usage) -> `docs/decisions/016-telegram-mini-app.md`, `docs/runtime.md`; checks: `docs/verifying.md` §2 and §5
- Domain terms -> `CONTEXT.md`
- New ADR -> `docs/decisions/NNN-title.md`
- Deploy bot to droplet -> `.claude/skills/deploy-bot/SKILL.md` (slash: `/deploy-bot`)
- Change the bot's routing, cards or buttons -> `docs/runtime.md` (routing table, card lifecycle), then `docs/verifying.md` §3
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
Hooks on `git commit`: ruff (`--fix` + format), ty (staged python), check_layers (full repo).
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

## Workflows index
`docs/workflows-index.md` (regen by create-workflow skill).
