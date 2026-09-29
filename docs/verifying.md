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

`notes-web`: `NOTES_DB_PATH=/tmp/n.sqlite3 uv run notes-web --port 18082`, then `curl /healthz`.
A foreign `Host:` header must get a 400.

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
IP=$(terraform -chdir=infrastructure/terraform output -raw droplet_ipv4)
C="docker compose -f /opt/ai_agents/src/infrastructure/docker/docker-compose.yml"
ssh root@$IP "$C logs --since 10m bot | grep -ciE 'traceback|error|notes disabled'"   # expect 0
ssh root@$IP "$C exec -T bot notes-smoke https://youtu.be/dQw4w9WgXcQ"
```

- **Agents:** preview and estimate every agent inside the new image. This is free and exercises
  parsing, pricing and the YouTube route through `warp`:
  `WORKFLOW.preview(settings, WORKFLOW.config_type(), source)`, then `WORKFLOW.estimate(...)`.
  Run it via `$C exec -T bot python -`.
- **Rollback point:** before a risky deploy, run `docker tag ai_agents:latest ai_agents:rollback-<n>`
  on the droplet and back up the sqlite files. To roll back, redeploy the last good commit.

## 5. Owner in Telegram (last)

Real taps are the only check of Telegram rendering and of real accounts. Hand the owner a short
list: what to send, what should appear, and which buttons to tap.
