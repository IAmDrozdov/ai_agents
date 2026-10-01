# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root: product vocabulary.
- **`apps/notes/CONTEXT.md`** for notes-app work. Its **Source** (the platform a Link came from) is not the root **Source**.
- **`docs/decisions/`**: ADRs touching the area you're about to work in. They are binding.

If any of these files don't exist, **proceed silently**. The `/domain-modeling` skill creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo with one app-scoped glossary:

```
/
├── CONTEXT.md
├── docs/decisions/
│   ├── 012-workflow-job-contract.md
│   └── 015-apps-layer-and-notes.md
└── apps/notes/CONTEXT.md
```

New ADRs: `docs/decisions/NNN-title.md`, numbered after the latest (next: 018).

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-012 (workflow job contract), but worth reopening because…_
