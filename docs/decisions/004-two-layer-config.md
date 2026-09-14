# ADR-004: Configuration in two layers

## Status
Accepted. Amended 2026-09-13: per-deployment operator policy of an interface (the bot's `BOT_*` spend caps and default/offered languages) is layer 1; workflow behaviour stays layer 2.

## Context
Config sprawl is the #1 monorepo rot. Mixing env vars with workflow knobs means rotating an API key requires editing Python, or tuning temperature requires editing `.env`. Both wrong.

## Decision

### Layer 1: `shared.config.Settings` (BaseSettings)
- Reads `.env` at repo root + environment vars.
- Contains ONLY:
  (a) secrets (API keys, tokens)
  (b) machine-different (paths, hosts)
  (c) infrastructure (log level, telemetry endpoints)
- Single instance per process: `from shared.config import settings`

### Layer 2: `workflows/<name>/src/<name>/config.py`
- Pydantic BaseModel (NOT BaseSettings).
- Workflow-specific knobs: model names, temperatures, prompts, retries, node lists.
- Defaults hardcoded in Python. NO env reading. NO `.env` lookup.
- Instantiated by interface layer, passed to `build_graph`.

## Banned
- WorkflowConfig reading `os.environ`
- Settings containing model names/temperatures
- Per-workflow `.env` files
- Reading config inside a node (nodes receive config via `build_*_node(settings, config)`)

## Why split
- Settings = "what's outside this code" (infrastructure)
- Config = "what this workflow does" (logic)

## Consequences
+ Clear separation: secrets vs behavior
+ Workflow knob change = code change (reviewable, version-controlled)
+ Key rotation = `.env` change only
- Two files instead of one (acceptable: clarity wins)

## Revisit when
Never. This is foundational.
