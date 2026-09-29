# Conventions

## Naming

- workflow dir: `snake_case`
- node file: `snake_case.py`
- workflow config class: `<Name>Config`
- workflow state type: `<Name>State`
- node builder: `build_<node>_node(settings, config, progress) -> Runnable`
- graph builder: `build_graph(settings, config, progress) -> Runnable | CompiledGraph`
- descriptor: `WORKFLOW: shared.job.Workflow` in `runtime.py`, re-exported from `__init__.py`

## File rules

- One node per file.
- Compose in `graph.py` — the only composition; `runtime.py` calls it, never re-chains nodes.
- Nodes report through the `Progress` object (`phase` on entry, `tick` per unit) and append their `CostLine`/`Fact`s to state; nothing else re-keys results.
- Workflow configs compose `shared` specs (`TranslateSpec`, `SpeechSpec`, `SttSpec`); no price tables in workflows (`shared.pricing`).
- `graph.py` first line declares framework + reason.
- Non-trivial business logic must be documented in workflow README or dedicated business spec in `docs/`.

## Import + boundary rules

- Use absolute imports across packages.
- Use relative imports inside workflow package.
- No wildcard imports.

Must match `tools/check_layers.py`:
- `interfaces/*` may import `shared.*`, `workflows.*`.
- `interfaces/*` must not import LLM SDK roots.
- `shared/*` must not import `workflows.*`, `interfaces.*`.
- `workflows/<a>/*` must not import `workflows/<b>/*`.
- `workflows/*` must not import `interfaces/*`.
- `apps/*` may import `shared.*` only (plus third-party libs other than transport frameworks); apps use absolute imports (`notes.domain.items`), as they came from their own repo (ADR-015).

## Config split (ADR-004)

- `shared.config.Settings` = env-driven infra config, plus the bot's per-deployment operator policy (`BOT_*`: spend caps, default and offered languages).
- `<Name>Config` = workflow behavior knobs with code defaults.
- Nodes do not read env and do not construct `Settings()`.
- Interfaces may pass config override payloads.

## Logging

- Workflow/node: no `print()`. Use `shared.obs.get_logger(__name__)`.
- Interface output: transport-native output (JSON body) is fine.

## External API budget

- Paid/quota APIs must be explicit opt-in.
- Default smoke/example run should avoid paid usage.
- Interface flags/payload must expose enable/disable clearly.

## Tracing

- OTEL tracing optional (`OTEL_ENABLED`); bootstrap via `shared/obs/tracing.py`.
- Local-first: everything works with tracing off.

## Smoke runs

- Every workflow is runnable through `uv run smoke <id> <path-or-url>` (ADR-001, ADR-012).
- The runner previews and prices first and asks before any paid call; `--yes` skips the prompt.
