# AGENTS.md

Map. Follow links. No rule duplication here. Humans start at `README.md`.

## What this is
Monorepo of local AI workflows exposed through one job contract (`shared.job`, ADR-012) by a private Telegram bot and a terminal smoke runner. New interfaces are thin adapters holding a registry of workflow descriptors. No automated tests (ADR-001).

## Read first
1. `docs/architecture.md` — layers, deps, interface exposure flow
2. `docs/conventions.md` — naming, layout, configs, business-doc conventions
3. `docs/decisions/` — ADRs. Read all.
4. `docs/tooling.md` — uv, ruff, ty, pre-commit, layer checker, grype
5. `docs/approaches-skills-rules-map.md` — approach -> skill -> binding rules

## Common tasks
- New workflow -> `.skills/create-workflow.md`
- New node -> `.skills/create-node.md`
- Run a workflow from the terminal -> `uv run smoke <id> <path-or-url>`
- Domain terms -> `CONTEXT.md`
- New ADR -> `docs/decisions/NNN-title.md`
- Deploy bot to droplet -> `.claude/skills/deploy-bot/SKILL.md` (slash: `/deploy-bot`)

## Hard layer rules (enforced by `tools/check_layers.py` + pre-commit)
- `interfaces/*` MAY import: `shared.*`, `workflows.<any>`.
- `interfaces/*` MUST NOT import: `langchain`, `langchain_core`, `langchain_community`, `langgraph`, `openai`, `anthropic`.
- `shared/*` MUST NOT import: `workflows.*`, `interfaces.*`.
- `workflows/<a>/*` MUST NOT import: `workflows/<b>/*`.
- `workflows/*` MUST NOT import: `interfaces/*`.

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
Py 3.12+, uv workspaces, Ruff, ty, Pydantic, LangChain (primary), LangGraph (justified), aiogram Telegram bot + FastAPI usage dashboard, pre-commit.

## Workflows index
`docs/workflows-index.md` (regen by create-workflow skill).
