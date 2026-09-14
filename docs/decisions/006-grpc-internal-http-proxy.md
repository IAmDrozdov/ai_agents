# ADR-006: Internal gRPC runtime + HTTP proxy for frontend

## Status
Superseded (2026-07-22). The gRPC runtime and CLI were removed together with
the only workflow that used them (`stock_researcher`). `interfaces/http` now
calls workflow runtimes in-process. Revisit a runtime transport layer only if
multi-service deployment returns.

## Context
Today workflows are exposed via CLI only. Frontend needs network API, but direct frontend-to-workflow access is poor fit:
- frontend cannot speak workflow internals
- HITL (interrupt/resume) needs sessioned protocol
- transport concerns must stay outside workflow logic

ADR-005 already requires thin interfaces and allows adding HTTP/gRPC adapters.

## Decision
- Internal service-to-service API is gRPC in `interfaces/grpc`.
- Frontend API is separate HTTP proxy in `interfaces/http`, only translating HTTP <-> gRPC.
- Workflow logic stays in `workflows/*`; no prompts/LLM logic in interfaces.
- Runtime protocol is step-based: `StartRun`, `ResumeRun`, `GetRun`.
- MVP session state is in-memory, single instance, TTL-based cleanup.

## Why
- Strong typed contract for internal consumers.
- Natural model for HITL and polling/reconnect.
- Keeps frontend-friendly HTTP while preserving internal runtime boundary.
- Avoids duplicating workflow behavior across interfaces.

## Consequences
+ Clear interface separation: internal gRPC, external HTTP.
+ Generic contract can onboard new workflows through registry entry.
+ Frontend can complete multi-step runs without direct workflow coupling.
- In-memory sessions are non-durable; restart loses in-flight runs.
- Single-instance limitation in MVP.

## MVP limits
- No persistence of run/session state.
- No authn/authz in transport layer.
- No streaming API; polling via `GetRun`.

## Revisit when
- Need horizontal scaling or durable resume after restart.
- Need strong auth boundary across environments.
- Need server-streaming updates to frontend.
