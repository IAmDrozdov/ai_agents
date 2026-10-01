---
name: live-test
description: Live test of a change in the real Telegram chat (Telegram Web, owner's Chrome) — the last rung before a bot, notes or Mini App task is called done. Use when every lower rung of docs/verifying.md is green, or when the owner says "live test", "прогони вживую", "проверь в телеге".
---

# Live test in the real chat

A task that changes what the owner sees in Telegram is **done** only after a live test of it passed
in the real chat. The owner approves the test script before it runs; you report "готово" only after
it ran green. Steps run in order; each ends on its criterion.

## 1. Preconditions

Lower rungs of `docs/verifying.md` (§1–§4) are green and you can name which ran. The change is live
on the droplet: only production polls the bot token. Deploying is part of the script (step 2), so
the owner's approval of the script is also the go for the deploy.

**Done when:** every lower rung is green, or the script says which one is skipped and why.

## 2. Draft the script

Write `.scratch/<feature>/live-test.md` from [script-template.md](script-template.md), in Russian.
Every user-visible behaviour the change adds or alters gets a case, plus one case per neighbouring
path the diff touched (regressions). A case is a **tracer**: one exact action (the literal text to
send, the button to tap), one observable expected result, and its cleanup. Test content is labelled
`🧪` and paid agent runs are out. You operate every case yourself, end to end: the owner's part
is approving the script, never executing steps.

Media the browser cannot produce (a voice message, a round video) comes from
`uv run python .claude/skills/live-test/send_media.py` (see its `--help`; OpenAI TTS, Russian): the
bot posts it into the chat and the case forwards it from there.

**Done when:** every changed behaviour maps to a case, every case has action + expected + cleanup,
and the file names its cost estimate and the deploy step.

## 3. Owner gate

Show the owner the script (path and the case list). Stop. The run starts on the owner's explicit
"да / ок / запускай"; a correction means revise the file and show it again.

**Done when:** the owner approved this exact version of the file.

## 4. Run

Deploy if the script says so (`/deploy-bot`). Then dispatch the run to a subagent
(`general-purpose`, `model: sonnet`): pass it the script path and
[telegram-web.md](telegram-web.md), and ask it to execute the cases in order, fill each case's
`Факт` and `PASS/FAIL` with evidence (message text, snapshot excerpt, screenshot path under
`.local/`), do every cleanup, and return the result table. The subagent follows the script
literally: a case it cannot execute as written is `BLOCKED` with the reason, never improvised.

**Done when:** every case is PASS, FAIL or BLOCKED in the file, and cleanup is confirmed (Items
total and Section counts back to the starting numbers).

## 5. Verdict

- All PASS: tell the owner the task is done, with the result table.
- Any FAIL: fix, re-climb the lower rungs, redeploy, rerun the failed cases. A new or changed
  action in the script goes back through step 3.
- BLOCKED: report it to the owner; a blocked case is not a pass.
