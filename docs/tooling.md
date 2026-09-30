# Tooling

## uv

- `uv sync --all-packages` install every workspace member into the one `.venv`
- `uv run <cmd>` run in the workspace env
- `uv add <pkg> --package <member>` add a dependency to a member
- Dev tools (ruff, ty, pre-commit) are the `dev` dependency group in the root `pyproject.toml`

## Ruff + ty

- `uv run ruff check .`
- `uv run ruff format .`
- `uv run ty check` (the pre-commit hook checks staged files only; run the full check yourself)

`.pre-commit-config.yaml` pins the same ruff version that `uv.lock` resolves for the `dev`
group; bump both together. Workspace members are declared `known-first-party` in
`pyproject.toml` so import sorting is identical in the venv and in the hook.

## pre-commit

Setup once:

```bash
uv run pre-commit install
```

This installs both the commit and the push hook (`default_install_hook_types`).

Hooks on commit:
- `ruff-check` (`--fix`)
- `ruff-format`
- `ty-check` (staged py)
- `check-layers` (full repo, always)
- `check-secrets` (`tools/check_secrets.sh`: trufflehog over the git history and the staged
  files, offline; needs `brew install trufflehog`)

Hook on push: `check-secrets` again, so a commit made with `--no-verify` still cannot leave.

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

The rules it enforces are listed in `docs/architecture.md` ("Enforced dependency rules").

Run:

```bash
uv run python tools/check_layers.py
```

## grype (dependency vulnerabilities)

`deploy.sh` runs it in its preflight, next to the secrets scan (ADR-017). By hand:

```bash
grype dir:. --only-fixed
```

Scans `uv.lock` and exits non-zero on High or worse (`fail-on-severity` in `.grype.yaml`, which
also holds the excludes and known false positives). Fix with `uv lock --upgrade-package <pkg>`
then `uv sync --all-packages`.
