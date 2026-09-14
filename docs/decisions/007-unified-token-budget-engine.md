# ADR-007: Unified token budget engine in shared layer

## Status
Superseded (2026-07-22). The engine (`shared/types/token_usage.py`,
`shared/obs/token_budget.py`) was removed with its only consumer
(`stock_researcher`). Re-add per this design if a future workflow needs
deterministic token stops.

## Context
`stock_researcher` added recursive company-intelligence flow. Cost/risk now depends on token usage across nodes, recursion depth, and optional LLM metadata. Existing telemetry logs usage but had no deterministic stop engine usable by all workflows.

## Decision
- Add shared budget primitives in `shared`:
  - `shared/types/token_usage.py`
  - `shared/obs/token_budget.py`
- `TokenBudgetPolicy` defines global cap, reserve, max depth, per-task caps.
- `TokenLedger` enforces stop decisions via `can_continue(task, depth)` and persists consumption via `record_usage(...)`.
- Unknown usage fallback estimator: `ceil(chars/4)` and mark `estimated=true`.
- Runtime/workflow outputs expose `budget_status` and `stop_reasons`.
- Telemetry schema gains `budget_events` with `budget_check`, `budget_consume`, `budget_stop`.

## Consequences
+ Deterministic cost guardrails with explainable stop reasons.
+ Shared implementation reusable by future workflows and interfaces.
+ Compatible with current gRPC/HTTP contracts (`Struct` payload).
- Additional state fields and reporting surface in workflow outputs.
- Estimator path is approximate when provider usage metadata is absent.

## Revisit when
A workflow needs provider-specific tokenizer precision that cannot be represented by current fallback estimator.
