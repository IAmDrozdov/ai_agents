# ADR-002: uv workspaces, single venv

## Status
Accepted

## Context
This monorepo is intentionally coupled:
- shared infrastructure package: `shared`
- workflow packages: `workflows/*`
- interface packages: `interfaces/*` (HTTP server; more adapters may follow)

All members are developed and run together in local/dev workflows, so one workspace-managed environment is preferred.

## Decision
- Root `pyproject.toml` declares `[tool.uv.workspace]` members: `shared`, `workflows/*`, `interfaces/*`.
- One root `.venv/` is managed by uv.
- Each member keeps its own `pyproject.toml` dependencies.
- Cross-member dependencies use `[tool.uv.sources] <name> = { workspace = true }`.

## Banned
- Per-workflow virtual environments.
- Editable-install dependency chains as environment strategy.
- `sys.path` hacks to reach workspace packages.

## Consequences
+ One `uv sync` keeps all members aligned.
+ Cross-package refactors are atomic.
+ Shared toolchain behavior (ruff, ty, pre-commit) is consistent.
- Dependency conflicts across members force a split if they become irreconcilable.

## Revisit when
Two or more members require incompatible versions of a critical dependency.
