# ADR-003: LangChain primary, LangGraph only when justified

## Status
Accepted

## Context
Both frameworks viable. LangChain simpler: `prompt | llm | parser`, RunnableParallel, RunnableBranch. LangGraph powerful but adds state/cycle complexity. Default-LangGraph = overengineering risk.

## Decision
- Default: LangChain Runnable composition.
- LangGraph allowed ONLY if workflow has at least one of:
  (a) cycles/loops where agent decides retry
  (b) conditional branching on intermediate state
  (c) state persisting across multiple `.invoke()` calls
  (d) human-in-the-loop interrupt points
- `graph.py` first line: comment with framework + reason.
  - `# Framework: langchain  -- linear composition, no state`
  - `# Framework: langgraph  -- conditional branch on review_score`
- Mixed allowed: LangGraph node may use LangChain Runnable internally. Reverse banned.

## Consequences
+ Simple workflows stay simple
+ LangGraph used means there's a real reason
+ First-line comment makes framework grep-able
- Migrating LangChain → LangGraph requires rewrite (acceptable: rare)

## Revisit when
3+ workflows need cross-cutting state/orchestration patterns LangChain can't express.
