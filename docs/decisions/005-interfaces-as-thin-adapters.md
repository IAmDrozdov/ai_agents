# ADR-005: Interfaces are thin adapters

## Status
Accepted. Amended 2026-09-13: the HTTP/web interfaces named in Context were deleted by ADR-013; the `cli` layer in the rules block below no longer exists.

## Context
This repo ships an HTTP interface and may add more (e.g. Telegram bot).
Without strict boundaries, business logic can leak into transport layers and diverge across interfaces.

## Decision

`interfaces/` does only transport work:
1. Receive and validate transport input.
2. Build settings/config override payload.
3. Invoke workflow runtime entrypoint.
4. Map output/errors to transport response shape.

Interfaces must not:
- import or orchestrate LLM SDKs directly
- contain prompts/templates or scoring/business rules
- implement workflow retries/fallback/model routing
- cache workflow-level LLM decisions

Thin adapter is a behavior contract, not a strict line-count rule.

## Layer dependency rules

```
interfaces/* MAY import: shared.*, workflows.<any>
interfaces/* MUST NOT import: langchain*, langgraph*, openai, anthropic
shared/* MUST NOT import: workflows.*, interfaces.*, cli
workflows/<a>/* MUST NOT import: workflows/<b>/*
workflows/* MUST NOT import: interfaces/*, cli
```

Enforced by `tools/check_layers.py` and pre-commit.

## Why
- Same workflow input should produce equivalent behavior across CLI and HTTP.
- New transports should be added by adapter code, not by moving business logic.
- Workflow reasoning remains inspectable in one place (`workflows/*`).

## Consequences
+ Clean transport/workflow separation.
+ Faster interface additions (HTTP/Telegram/CLI) with lower regression risk.
+ Mechanical drift prevention via layer checks.
- Some adapter boilerplate remains necessary per workflow/interface.

## Revisit when
This remains foundational unless architecture intentionally abandons layer isolation.
