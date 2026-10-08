# Skill: Create new workflow

Create a new workflow package under `workflows/` that exports a job descriptor (ADR-012) and register it in the bot.

## Inputs from user
- workflow name (`snake_case`)
- one-line purpose
- framework: `langchain` (default) or `langgraph` (must satisfy ADR-003)

## Steps

1. Verify workflow name is unique under `workflows/`.

2. Create package layout:

```text
workflows/<name>/
├── pyproject.toml
├── README.md
└── src/<name>/
    ├── __init__.py          from .runtime import WORKFLOW
    ├── config.py
    ├── state.py
    ├── graph.py
    ├── runtime.py           preview / estimate / run / speed_profile + WORKFLOW
    ├── nodes/__init__.py
    └── optional: providers/
```

3. `pyproject.toml` baseline:

```toml
[project]
name = "<name>"
version = "0.0.0"
requires-python = ">=3.12"
dependencies = ["shared", "langchain-core>=0.3"]  # plus the provider SDKs the stages call, e.g. "openai>=1.0"
# add "langgraph>=0.2" only if framework=langgraph

[tool.uv.sources]
shared = { workspace = true }

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/<name>"]
```

4. `config.py`
- define `<Name>Config(BaseModel)` with workflow knobs only; compose shared specs
  (`TranslateSpec`, `SpeechSpec`, `SttSpec`) for provider stages instead of flat fields
- no env reading, no price tables (ADR-004, ADR-012)

5. `state.py`
- define `<Name>State` (`TypedDict`, `total=False`) carried between nodes
- always include `cost_lines: list[CostLine]`, `facts: list[Fact]`, `error`

6. `graph.py`
- first line: `# Framework: langchain|langgraph -- <reason>`
- expose `build_graph(settings, config, progress: Progress = NO_PROGRESS)` — the only composition
- nodes are `build_<node>_node(settings, config, progress)`

7. `README.md`
- purpose
- framework + justification
- node list
- run examples
- business behavior summary (or pointer to dedicated business spec)

8. `runtime.py` — the descriptor
- `preview(settings, config, source) -> Preview` (free, unbilled; put what run needs in `payload`)
- `estimate(settings, config, preview) -> Estimate` using the shared stage estimators
- `run(settings, config, preview, progress) -> Result` = `build_graph(...).invoke(...)` + mapping to `Result`
- `speed_profile(config) -> str`
- `WORKFLOW = Workflow(id=..., config_type=..., accepts=frozenset({...}), ...)`

9. Exposure
- add to `interfaces/smoke/src/smoke/registry.py` and run `uv run smoke <name> <source>`
- add a `RegistryEntry` in `interfaces/telegram_bot/src/telegram_bot/registry.py`
  (label, short label, hint keys, settings → config builder in `user_config.py`)

10. Update docs
- append to `docs/workflows-index.md`
- add/update business spec in `docs/` for non-trivial workflow logic
- update `docs/approaches-skills-rules-map.md` only if process changes

11. Validate

```bash
uv run pre-commit run --all-files
```

## Constraints
- No tests added (ADR-001).
- No env reads in workflow config (ADR-004).
- No LLM SDK imports in `interfaces/*` (ADR-005 + `tools/check_layers.py`).
- Cross-workflow imports are forbidden.

## Output
Summarize:
- files created/updated
- exposure completed (smoke registry + bot registry entry)
- the behavior and provider integration implemented, or the facts still needed to finish them
