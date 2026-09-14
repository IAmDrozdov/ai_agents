# Approaches -> Skills -> Rules map

| Approach | Use when | Primary skill | Binding rules / ADRs | Validate |
|---|---|---|---|---|
| New workflow | Add package in `workflows/*` | `.skills/create-workflow.md` | ADR-001/003/004/005, `docs/architecture.md` | `uv run pre-commit run --all-files` |
| New node | Add step/tool/LLM call in workflow | `.skills/create-node.md` | ADR-004/005, `docs/conventions.md` | `uv run pre-commit run --all-files` |
| Interface exposure | Add a registry entry in the bot for a workflow's `WORKFLOW` | `.skills/create-workflow.md` | ADR-005, ADR-012, `tools/check_layers.py` | `uv run smoke <id> <source>` |
| Business-rule change | Change scoring/threshold/risk behavior | `.skills/create-node.md` | ADR-004/005, workflow README + business spec | `uv run ty check` |
| Observability change | Change tracing behavior | `.skills/create-node.md` (workflow-side) | ADR-004/005, `docs/observability/tracing-elk.md` | `uv run pre-commit run --all-files` |
| Layer refactor | Move code across layers | `.skills/create-workflow.md` (boundary reference) | ADR-005, `docs/architecture.md`, `tools/check_layers.py` | `uv run python tools/check_layers.py` |
| ADR update/create | Add or revise architecture decision | `.skills/create-workflow.md` (doc checklist ref) | `docs/decisions/*`, ADR numbering consistency | `rg -n "ADR-" docs/decisions docs/*.md` |

Rule anchors:
- layer enforcement: `tools/check_layers.py`
- boundaries: `docs/architecture.md`
- conventions: `docs/conventions.md`
- checks: `docs/tooling.md`
