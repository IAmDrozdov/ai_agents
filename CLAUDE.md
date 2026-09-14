@AGENTS.md

# Claude Code adapter

`AGENTS.md` defaults apply. Claude-specific only here.

## Editing
- Edit tool for surgical changes. No full rewrites.
- Multi-file refactor: plan first, edit second.

## Validation before finishing
1. `uv run pre-commit run --all-files`
   (Runs ruff fix+format, ty, check_layers.)
2. If pre-commit not installed: `uv run ruff check . && uv run ty check && uv run python tools/check_layers.py`.

## When unsure
Read `docs/decisions/` first. ADRs binding.
