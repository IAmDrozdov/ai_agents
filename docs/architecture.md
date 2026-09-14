# Architecture

## Layers

```text
interfaces/   -> transport adapters: a registry of workflow descriptors + presentation
workflows/*   -> business logic + orchestration, exposed as one job descriptor each
shared/       -> env/settings, the job contract, pricing, document intake, provider stages
```

## Enforced dependency rules

Source of truth: `tools/check_layers.py`.

- `interfaces/*` MAY import `shared.*`, `workflows.<any>`.
- `interfaces/*` MUST NOT import `langchain*`, `langgraph*`, `openai`, `anthropic`.
- `shared/*` MUST NOT import `workflows.*`, `interfaces.*`.
- `workflows/<a>/*` MUST NOT import `workflows/<b>/*`.
- `workflows/*` MUST NOT import `interfaces/*`.

## Job contract (ADR-012)

`shared/job.py` defines what every interface needs from a workflow:

```text
Source (Document | Link) --preview--> Preview --estimate--> Estimate
                                      Preview --run(progress)--> Result(Deliverable, Cost, facts)
```

Each workflow exports `WORKFLOW: Workflow` from `runtime.py`. Interfaces iterate a
registry of descriptors and never branch on workflow ids.

## Workflow package shape

```text
workflows/<name>/
├── pyproject.toml
├── README.md
└── src/<name>/
    ├── __init__.py         exports WORKFLOW
    ├── config.py           <Name>Config composing shared specs + own knobs
    ├── state.py            TypedDict carried between nodes (internal)
    ├── graph.py            the single composition, takes Progress
    ├── runtime.py          preview / estimate / run / speed_profile + WORKFLOW
    ├── nodes/              build_<node>_node(settings, config, progress)
    └── providers/          (optional) data fetch
```

`graph.py` first line:
- `# Framework: langchain -- <reason>` or
- `# Framework: langgraph -- <reason>`

## Interface package shape

```text
interfaces/telegram_bot/src/telegram_bot/
├── __main__.py
├── registry.py         RegistryEntry per workflow (label, hint keys, build_config)
├── handlers/           transport: intake → estimate card → run
├── worker.py           FIFO queue, runs WORKFLOW.run, delivers Result
└── ...

interfaces/smoke/src/smoke/
├── __main__.py         uv run smoke <workflow> <path-or-url>
└── registry.py
```

## Thin-adapter rule

Interfaces do transport only:
- parse input into a `Source`
- build the workflow config from user settings
- call the descriptor (preview / estimate / run)
- render `Preview`, `Estimate`, `Result`

Interfaces never do prompts/scoring/retry/LLM orchestration and never read workflow
state dicts.

## Responsibility map

| Concern | Owner |
|---|---|
| keys/endpoints/env + bot operator policy (`BOT_*`) | `shared.config.Settings` |
| behavior knobs | `<workflow>.config.*` (composing `shared` specs) |
| prices, model ids, voices | `shared.pricing` |
| document parsing | `shared.doc.extract` |
| translate / speech / STT engines | `shared.translate`, `shared.audio` |
| job contract types | `shared.job` |
| transport parsing + presentation | `interfaces/*` |
| routing/state graph | `workflows/<name>/graph.py` |
| business node logic | `workflows/<name>/nodes/*` |
| data fetch | `workflows/<name>/providers/*` |
| descriptor (preview/estimate/run) | `workflows/<name>/runtime.py` |
| tracing bootstrap | `shared/obs/tracing.py` |
