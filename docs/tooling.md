# Tooling

## uv

- `uv sync --all-packages` install every workspace member into the one `.venv`
- `uv run <cmd>` run in the workspace env
- `uv add <pkg> --package <member>` add a dependency to a member
- Dev tools (ruff, ty, pre-commit) are the `dev` dependency group in the root `pyproject.toml`

## Ruff + ty

- `uv run ruff check .`
- `uv run ruff format .`
- `uv run ty check`

`.pre-commit-config.yaml` pins the same ruff version that `uv.lock` resolves for the `dev`
group; bump both together. Workspace members are declared `known-first-party` in
`pyproject.toml` so import sorting is identical in the venv and in the hook.

## pre-commit

Setup once:

```bash
uv run pre-commit install
```

Hooks on commit:
- `ruff-check` (`--fix`)
- `ruff-format`
- `ty-check` (staged py)
- `check-layers` (full repo, always)

Manual full run:

```bash
uv run pre-commit run --all-files
```

Emergency bypass only:

```bash
git commit --no-verify
```

Record reason in commit message.

## Layer checker

`tools/check_layers.py` = boundary source of truth.

Enforces:
- `interfaces/*` no imports: `langchain`, `langchain_core`, `langchain_community`, `langgraph`, `openai`, `anthropic`
- `shared/*` no imports: `workflows`, `interfaces`
- `workflows/<a>/*` no imports: `workflows/<b>/*`
- `workflows/*` no imports: `interfaces`

Run:

```bash
uv run python tools/check_layers.py
```

## grype (dependency vulnerabilities)

Before a deploy:

```bash
grype dir:. --only-fixed
```

Scans `uv.lock`; excludes and known false positives live in `.grype.yaml`. Fix with
`uv lock --upgrade-package <pkg>` then `uv sync --all-packages`.
