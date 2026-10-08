# Architecture

## Layers

```text
interfaces/   -> transport adapters: a registry of workflow descriptors + presentation
workflows/*   -> business logic + orchestration, exposed as one job descriptor each
apps/*        -> stateful products with their own domain and store, used by interfaces (ADR-015)
shared/       -> env/settings, the job contract, pricing, document intake, provider stages
```

## Enforced dependency rules

Source of truth: `tools/check_layers.py`.

- `interfaces/*` MAY import `shared.*`, `workflows.<any>`, apps (`notes`, `diary`).
- `interfaces/*` MUST NOT import `langchain*`, `langgraph*`, `openai`, `anthropic`.
- `shared/*` MUST NOT import `workflows.*`, `interfaces.*`, apps.
- `workflows/<a>/*` MUST NOT import `workflows/<b>/*`.
- `workflows/*` MUST NOT import `interfaces/*` or apps.
- `apps/*` MAY import `shared.*`; MUST NOT import `workflows.*`, `interfaces.*`, another app,
  or `aiogram`/`fastapi`/`starlette`/`uvicorn`. Apps report outward through callbacks.

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
├── routing.py          what an incoming message becomes (the Path); pure, no aiogram in route()
├── cards.py            CardBook: Estimate card state, intake port, rendering
├── notes_capture.py    the bot's Capture adapter: message → notes.capture.capture → settle
├── notes_runtime.py    NotesRuntime: Database, Classifier, background loops, notify
├── worker.py           FIFO queue, runs WORKFLOW.run, delivers Result
├── miniapp/            the admin Mini App: signed JSON API + static shell (ADR-016)
└── ...

interfaces/smoke/src/smoke/
├── __main__.py         uv run smoke <workflow> <path-or-url>
└── registry.py
```

## Apps (ADR-015)

An app is not a job: it keeps state across messages (an Item store, background retries), so
it does not go through `shared.job`. Shape:

```text
apps/notes/
├── pyproject.toml, README.md, CONTEXT.md (own glossary), docs/ (ADRs, spec, tickets)
└── src/notes/          domain/, capture.py, db.py, enrich/, classify/, sweeper.py, smoke.py
apps/diary/
├── pyproject.toml, README.md, CONTEXT.md (own glossary)
└── src/diary/          domain.py (every diary rule), db.py
```

The diary (ADR-020) has no chat side: only `telegram_bot/miniapp/api_diary.py` reaches it.

Its interfaces follow the same thin-adapter rule: `telegram_bot/handlers/notes.py` and
`notes_ui.py` parse and render, `telegram_bot/miniapp` serves the Mini App (ADR-016). The admin's single
website link gets the usual price card with a 💾 button on top (`documents.link_handler`, a savable Path);
invitees never see 💾.

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
| notes domain, store, enrichment, classifier port | `apps/notes/src/notes/*` |
| diary domain and store | `apps/diary/src/diary/*` |
| incoming message → Path | `telegram_bot/routing.py` |
| notes Telegram presentation / intake / Mini App | `telegram_bot/notes_ui.py`, `notes_capture.py`, `handlers/notes.py` / `telegram_bot/miniapp` |
