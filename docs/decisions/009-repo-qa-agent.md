# ADR-009: Codebase Q&A agent (repo_qa) over droplet-local clones

Status: Superseded by ADR-013 (2026-09-12) — the workflow was deleted; no caller remained.
Redacted 2026-09-13: employer and repository names removed for public release.

## Decision

1. New workflow `workflows/repo_qa`: a **LangGraph ReAct agent** (ADR-003 (a):
   model-driven tool-call cycles) that answers questions about private
   repositories using **agentic search** — ripgrep/read/glob/git-log tools over
   local clones — not embeddings RAG and not a symbol index. Freshness comes
   from `git pull`; there is no index to rebuild per commit.
2. Agent model: **Anthropic `claude-sonnet-5`** via `langchain-anthropic` — the
   repo's first non-OpenAI provider, confined to this workflow (interfaces still
   may not import LLM SDKs, ADR-005). Voice questions are transcribed with
   OpenAI STT (`gpt-4o-mini-transcribe`). System prompt carries a
   `cache_control` block: the prefix is re-read on every tool cycle, so prompt
   caching is the dominant cost lever.
3. The repos (three private clones) live on the droplet at
   `/opt/ai_agents/repos`, cloned over HTTPS with a **fine-grained read-only
   PAT** (deploy keys rejected: GitHub binds one key to one repo) and updated by
   a **host cron every 5 minutes** (`infrastructure/setup_repos.sh`). Webhooks
   rejected: the droplet firewall is SSH-only (ADR-008) and local git hooks
   miss colleagues' commits. The container mounts the clones **read-only** at
   `/repos`; agent tools are path-jailed and never execute a shell.
4. Telegram exposure: `/ask` (menu command), text or voice, **admin-only** —
   invited friends must not see private code. Short answers are sent as
   Telegram HTML; long ones are rendered to PDF (markdown-it-py + pygments +
   weasyprint in `repo_qa/reporting/`), falling back to a `.md` file.
   HTTP exposure: `POST /v1/repo-qa`. Web UI deliberately not wired — the
   clones exist only on the droplet.

## Context

The owner answers "how does X work in our codebase" questions from colleagues
via Cursor/Claude Code when at the computer; away from it, only the Telegram
bot is available. The repos are small enough that full clones on the droplet
are trivial. The code owner approved hosting the clones on the personal droplet
and sending code fragments to Anthropic (answers) / OpenAI (voice transcription).

## Consequences

- New secret `ANTHROPIC_API_KEY`; new Settings field `repo_qa_root`.
- Docker image gains `ripgrep`, `git`, and weasyprint's pango/fonts stack
  (~100 MB).
- Questions run through the existing single-worker FIFO queue and usage log;
  a question is a `Job` with `question` instead of file bytes.
- ~$0.05–0.3 and 30–90 s per question (10–20 tool calls, cache reads at 0.1×).
- Revisit if: answers regularly miss code that content-grep cannot reach
  (consider a symbol index as an extra tool), or the 5-minute
  staleness window becomes a real problem.
