# Rolling back a deploy

A deploy that changes the image tags the one that was running as `maxi_bot:previous` (a re-run
with no changes leaves it alone), so the fast rollback needs no rebuild:
```bash
./infrastructure/ssh-gate.sh ssh 'docker tag maxi_bot:previous maxi_bot:latest && docker compose -f /opt/maxi_bot/src/infrastructure/docker/docker-compose.yml up -d'
```
`previous` moves on every deploy that changes the image. To keep a point across several deploys, tag it yourself
(`docker tag maxi_bot:latest maxi_bot:rollback-<n>` on the droplet) and delete the tag when it is
no longer needed. The droplet has no git history, so going further back means redeploying older
code from your machine:
```bash
git stash            # or check out the last good commit
./infrastructure/deploy.sh
git stash pop
```
The sqlite volume (`/data/telegram_bot.sqlite3`, `/data/notes.sqlite3`) is untouched by
deploys; users, settings, usage history and notes survive. Before a schema-affecting change,
take a Backup (ADR-018; `infrastructure/README.md` "Backups"). Never copy the WAL files by hand:
```bash
SSH_KEY=~/.ssh/<key> uv run python infrastructure/backup.py run --force
```
