# Contributing

This is a personal project published so others can run their own copy. Pull requests
are welcome and are reviewed at the owner's pace.

## Before you start

- Read `AGENTS.md` (the map), `docs/architecture.md`, `docs/conventions.md` and the ADRs
  in `docs/decisions/`. ADRs are binding; changing a decision means adding a new ADR or an
  `Amended <date>` line to the existing one.
- Layer rules are enforced by `tools/check_layers.py`; a PR that breaks them fails the gate.
- There are no automated tests by design (ADR-001). Verify a change with the smoke runner:
  `uv run smoke <workflow> <path-or-url>` previews and prices first and asks before paying.

## The gate

Every change must pass, locally, before it is pushed:

```bash
uv sync --all-packages
uv run pre-commit install        # once
uv run pre-commit run --all-files
```

That runs ruff (fix + format), ty, the layer checker and a secrets scan. The scan needs
`trufflehog` on your PATH (`brew install trufflehog`) and also runs when you push.

## Scope that needs a conversation first

Open an issue before: adding a dependency to `shared/`, touching auth or secrets handling,
cross-workflow refactors, new top-level folders, or reaching for LangGraph (ADR-003).

## Adding a workflow or node

Follow `.skills/create-workflow.md` and `.skills/create-node.md`; register the workflow in
both `interfaces/smoke` and `interfaces/telegram_bot` and add it to `docs/workflows-index.md`.
