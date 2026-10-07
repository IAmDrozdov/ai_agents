# Verifying a change without tests

The repo has no automated tests (ADR-001), so keep everything below in a scratch directory,
never in the repo. Climb this ladder until the change is covered, and report which rungs ran.

## 1. Static gate (always)

```bash
uv run pre-commit run --all-files   # ruff, format, check_layers; ty covers staged files only
uv run ty check                     # full type check; run it too
```

To confirm a new layer rule bites, plant a forbidden import (e.g. `import aiogram` under
`apps/`), check that `check_layers` fails, then remove it.

## 2. Smoke runs (real code paths, local)

```bash
uv run smoke <workflow> <path-or-url>            # preview + price are free; it asks before paying
uv run notes-smoke <url-or-text>                 # fetch + classify one input; prints the Filing
uv run notes-smoke http://169.254.169.254/       # the SSRF guard must refuse it
NOTES_CLASSIFIER_PROVIDER=fake uv run notes-smoke <url>   # offline classifier, no spend
```

The Mini App needs no bot token: `MINIAPP_INIT_SECRET` stands in for the derived key.

```bash
T=$(mktemp -d); SECRET=$(python3 -c 'import hashlib,hmac;print(hmac.new(b"WebAppData",b"42:TEST",hashlib.sha256).hexdigest())')
ADMIN_TELEGRAM_ID=100 TELEGRAM_DB_PATH=$T/b.sqlite3 NOTES_DB_PATH=$T/n.sqlite3 MINIAPP_INIT_SECRET=$SECRET \
  uv run telegram-miniapp --port 18083
```

Sign test initData in a scratch script: `hash` is the hex HMAC-SHA256, keyed with `SECRET`, of the
sorted `key=value` lines (every field except `hash`, `signature` included); set `auth_date` to
now and `user` to `{"id":100,...}`. Then check `/api/usage`: no header → 401, admin → 200, another
user id → 403, a tampered `hash` → 401, an `auth_date` 25 h old → 401. To see the pages, open
`http://127.0.0.1:18083/#tgWebAppData=<url-encoded initData>&tgWebAppVersion=8.0&tgWebAppPlatform=web`
(`telegram-web-app.js` reads the hash; the app has no auth bypass). Use an isolated browser
context and device emulation for a phone viewport; do not resize the owner's window. A layout
change is not done until, at 320 and 393 px, every tab has `scrollWidth == clientWidth`, every
form control computes to at least 16 px, and a `PerformanceObserver` on `layout-shift` reads 0
while a chip, filter or status is tapped.

## 3. Offline bot harness (routing, cards, callbacks, no token)

Drive the real `Dispatcher` with synthetic updates and a recording session. This covers "who
handles what", button layouts, races and invitee vs admin behaviour. Anything the bot sends
comes back as a recorded Bot API call.

```python
import os, tempfile; T = tempfile.mkdtemp()
os.environ.update(ADMIN_TELEGRAM_ID="100", TELEGRAM_DB_PATH=f"{T}/b.sqlite3",
                  NOTES_DB_PATH=f"{T}/n.sqlite3", OPENAI_API_KEY="sk-test")
# ↑ before importing anything from shared/telegram_bot: Settings is read at import

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message
from telegram_bot import access, db
from telegram_bot.access import AccessMiddleware
from telegram_bot.handlers import documents, notes, setup_routers
from telegram_bot.worker import JobQueue

class Rec(BaseSession):
    def __init__(self): super().__init__(); self.calls = []; self.mid = 1000
    async def close(self): pass
    async def stream_content(self, *a, **k): yield b""
    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if isinstance(method, SendMessage):
            self.mid += 1
            return Message(message_id=self.mid, date=0, text=method.text,
                           chat=Chat(id=int(method.chat_id), type="private"),
                           reply_markup=method.reply_markup).as_(bot)  # .as_(bot) or edits fail
        return True

db.init_db()
db.redeem_invite(access.mint_invite(100), 300, "inv", "Inv")      # user 300 = invitee
bot = Bot(token="42:TEST", session=(tg := Rec()))
dp = Dispatcher(); dp["queue"] = JobQueue()
dp["notes"] = notes.build_runtime()          # or NotesRuntime(db=..., http=fake, classifier=FakeClassifier())
dp.update.outer_middleware(AccessMiddleware()); setup_routers(dp)
# await dp.feed_update(bot, Update(update_id=1, message=Message(..., from_user=User(id=100,...))))
```

- **Network:** stub it at the module seam. Set `documents.scrape_url` to a function returning a
  `ScrapedArticle`, give the notes runtime a fake `http`, and avoid YouTube links, because
  `yt_dub` preview goes online.
- **Callbacks:** feed `CallbackQuery(data=JobCB(action="save").pack(), message=<the card>)`.
- **Races:** start the message feed as a task, tap while the (stubbed) scrape sleeps, then
  assert on the final edit.
- **Worth asserting on every bot change:**
  - an invitee's card has no 💾 and its status line has no keyboard;
  - an invitee's plain text is ignored;
  - the admin's commands still reach their routers;
  - a document never becomes a note.

## 4. Production, after `deploy.sh` (free)

```bash
G=./infrastructure/ssh-gate.sh   # SSH is closed by default; the gate opens it for one command (ADR-017)
C="docker compose -f /opt/ai_agents/src/infrastructure/docker/docker-compose.yml"
$G ssh "$C logs --since 10m bot | grep -ciE 'traceback|error|notes disabled'"   # expect 0
$G ssh "$C exec -T bot notes-smoke https://youtu.be/dQw4w9WgXcQ"
```

- **Agents:** preview and estimate every agent inside the new image. This is free and exercises
  parsing, pricing and the YouTube route through `warp`:
  `WORKFLOW.preview(settings, WORKFLOW.config_type(), source)`, then `WORKFLOW.estimate(...)`.
  Run it via `$C exec -T bot python -`.
- **Mini App:** on the droplet (outside your tailnet, so it is the public path), `curl -fsS
  $BOT_MINIAPP_URL/healthz` must answer and `/api/usage` without a header must be 401.
  `docker stats --no-stream` should sit inside the memory caps.
- **Rollback point:** a deploy that changes the image tags the one that was running as
  `ai_agents:previous`. To roll back, run `docker tag ai_agents:previous ai_agents:latest && $C up -d` on the droplet. Tag a
  manual `ai_agents:rollback-<n>` only to keep a point across more than one deploy, and take a
  Backup before a schema change (`SSH_KEY=… uv run python infrastructure/backup.py run --force`,
  ADR-018).

## 5. Telegram Web (the real chat), then the owner

Only production polls the bot token, so the real chat is the only place to exercise the menu
button, cards and `web_app` buttons. Every change the owner sees in Telegram ends here, run by the
`live-test` skill (`.claude/skills/live-test/`): a script the owner approves first, then a run in
the owner's logged-in Telegram Web through the `chrome-devtools` MCP. The skill's `telegram-web.md`
holds the guardrails and mechanics; which Chrome profile and which chat URL are machine facts in
`CLAUDE.local.md` (gitignored, because this repo is public). The agent runs every case itself;
voice and round-video messages come from the skill's `send_media.py`.
