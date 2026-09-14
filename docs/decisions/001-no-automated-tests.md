# ADR-001: No automated tests

## Status
Accepted. Amended 2026-09-13 (ADR-012): per-workflow `examples/run.py` scripts are gone; the smoke surface is `uv run smoke <id> <path-or-url>`.

## Context
Personal monorepo, local agents. Not deployed, no SLA, no team. LLM tests expensive: mocks misleading, real LLM costly+slow. Owner opts out.

## Decision
- No pytest, unittest, test dirs, CI test runs.
- Every workflow is runnable end-to-end with realistic input through the smoke runner (`uv run smoke <id> <path-or-url>`, ADR-012).
- `shared/` validated by use in workflows. Break = signal.

## Consequences
+ Zero test maintenance
+ No mock-LLM theater
+ Smoke runs = the reference for how a workflow behaves
- Silent `shared/` regressions until next workflow run
- Manual run-all on refactor (acceptable: small N)

## Non-decisions
- Linters (Ruff) + structural checks (`tools/check_layers.py`) ARE used. Not tests.
- Type check (`ty`) IS used. Not a test.
- pre-commit hooks ARE used. Not tests.

## Revisit when
Single `shared/` change silently breaks 3+ workflows.
