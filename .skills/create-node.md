# Skill: Create new node inside workflow

Create one workflow node file and wire exports, keeping business logic in workflow layer.

## Inputs from user
- parent workflow name
- node name (`snake_case`)
- node purpose (one line)

## Steps

1. Verify parent workflow exists: `workflows/<workflow>/`.

2. Create node file:
`workflows/<workflow>/src/<workflow>/nodes/<node>.py`

```python
"""<purpose>"""

from __future__ import annotations

from langchain_core.runnables import Runnable, RunnableLambda

from shared.config import Settings
from shared.job import NO_PROGRESS, Progress
from shared.obs import get_logger

from ..config import <Workflow>Config
from ..state import <Workflow>State

log = get_logger(__name__)


def build_<node>_node(
    settings: Settings, config: <Workflow>Config, progress: Progress = NO_PROGRESS
) -> Runnable:
    """<purpose>"""

    def _run(state: <Workflow>State) -> dict:
        if state.get("error"):
            return dict(state)
        progress.phase("<node>", 1)
        # ... business behavior; append any CostLine to state["cost_lines"] and Facts to state["facts"]
        return {**state}

    return RunnableLambda(_run, name="<node>")
```

3. Update node exports:
`workflows/<workflow>/src/<workflow>/nodes/__init__.py`

```python
from .<node> import build_<node>_node
```

Append to `__all__` if present.

4. Wire in graph (suggest + optionally edit if requested)
- import builder in `graph.py`
- instantiate via `build_<node>_node(settings, config, progress)`
- connect graph edges/branches in workflow orchestration

5. Update workflow docs
- add node to `workflows/<workflow>/README.md`
- if node changes business behavior materially, update business spec in `docs/`

6. Validate

```bash
uv run pre-commit run --all-files
```

## Constraints
- Node receives `settings` and `config`; never instantiates `Settings()`.
- No `print()` in node; use `shared.obs` logger.
- One node per file.
- Node composition belongs in `graph.py` only; `runtime.py` holds the descriptor and calls the graph.
- Do not move business logic into interfaces.

## Output
Summarize:
- created node file
- export updates
- graph wiring status
- remaining TODOs for node internals and docs
