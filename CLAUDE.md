@AGENTS.md

# Claude Code adapter

`AGENTS.md` defaults apply. Claude-specific only here.

## Editing
- Edit tool for surgical changes. No full rewrites.

## Context economy
Every call re-reads the whole context, so a token added early is paid again on each later call.
- Read narrowly: locate first (`rg -n`; absence checks per RTK.md), then `Read` with offset/limit
  (it also satisfies Edit's read-first check). Cap command output (`| tail -20`). Batch independent reads and edits in one turn.
- Production state: `infrastructure/droplet.sh status|logs|sql|py`, one gated call each.
- A phase boundary (plan approved, tickets written, deploy verified, report delivered), a new topic
  once context passes ~250k, or a pause of more than an hour leaves its handoff in a file. Say in
  one line that it is a `/clear` point and name the file to resume from.
- Waiting: one blocking call (an until-loop inside one command) or the background task's completion
  notice, instead of repeated `tail`/`sleep` calls. A Monitor filter matches only terminal lines
  (`ERROR|Traceback|done`).

## Validation before finishing
1. `uv run ruff check --fix <changed files> && uv run ruff format <changed files>`, then
   `uv run pre-commit run --all-files > .local/pre-commit.log 2>&1; echo "exit=$?"; grep -E 'Passed|Failed' .local/pre-commit.log`
   (ruff, ty, check_layers, check_secrets); on a non-zero exit read the failing hook in the log.
2. If pre-commit not installed: `uv run ruff check . && uv run ty check && uv run python tools/check_layers.py`.
3. Behaviour changes: climb `docs/verifying.md` and report which rungs ran.
4. A change the owner sees in Telegram (bot, notes, Mini App): done only after the `live-test`
   skill ran green — the owner approves its script before it runs.

## When unsure
Read the ADRs in `docs/decisions/` that touch the area. ADRs binding.

# Compact instructions
Keep the owner's decisions and constraints in their words; what was tried and ruled out, and why;
the current state (files changed, deployed or not, which `docs/verifying.md` rungs ran); open items;
exact identifiers (ADR numbers, paths, commit hashes, Item ids). Drop file contents and command
output that can be read again.
