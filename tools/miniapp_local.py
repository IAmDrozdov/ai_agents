"""Dev launcher: run the admin Mini App on throwaway DBs with a signed local URL (docs/verifying.md §2)."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

REPO_ROOT = Path(__file__).resolve().parent.parent
WORK = REPO_ROOT / ".local" / "miniapp-local"
URL_FILE = REPO_ROOT / ".local" / "miniapp_url.txt"
PID_FILE = WORK / "miniapp.pid"
LOG_FILE = WORK / "server.log"
NOTES_DB = WORK / "notes.sqlite3"
BOT_DB = WORK / "bot.sqlite3"

TEST_ADMIN_ID = 100  # the only id the local server admits
HOST = "127.0.0.1"
SOURCE_NOTES = "notes.sqlite3"
SOURCE_BOT = "telegram_bot.sqlite3"


def init_secret(token: str) -> str:
    """Hex of HMAC("WebAppData", token), the same derivation as infrastructure/deploy.sh."""
    return hmac.new(b"WebAppData", token.encode(), hashlib.sha256).hexdigest()


def sign_init_data(secret: str) -> str:
    """URL-encoded initData signed the way Telegram does; the key is the raw bytes of the hex secret."""
    fields = {
        "query_id": "AAHlocal",
        "user": json.dumps({"id": TEST_ADMIN_ID, "first_name": "Local"}, separators=(",", ":")),
        "auth_date": str(int(time.time())),
        "signature": "bG9jYWwtc2lnbmF0dXJl",
    }
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    key = bytes.fromhex(secret)
    fields["hash"] = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def launch_url(port: int, secret: str) -> str:
    """The page URL carrying initData in the fragment, as telegram-web-app.js expects."""
    data = quote(sign_init_data(secret), safe="")
    return f"http://{HOST}:{port}/#tgWebAppData={data}&tgWebAppVersion=8.0&tgWebAppPlatform=web"


def seed_notes(path: Path) -> None:
    """A few 🧪 Sections and Items across statuses, a Link, a Note and an overdue reminder."""
    from notes.db import Database
    from notes.domain import items, reminders, sections

    db = Database(str(path))
    db.init()
    lab = sections.create_section(db, name="🧪 Lab", emoji="🧪", color="#7a5cff", hint="local test")
    spare = sections.create_section(
        db, name="🧪 Spare", emoji="🧪", color="#1fa37a", hint="local test"
    )
    now = datetime.now(UTC)
    for i in range(6):
        created = now - timedelta(days=i, hours=i)
        capture = items.capture_link(
            db, f"https://example.com/local-{i}", f"🧪 link {i}", now=created
        )
        items.store_enrichment(
            db,
            capture.item.id,
            sections=[(lab.slug, spare.slug, "watch")[i % 3]],
            title=f"🧪 Link {i}",
            gist=f"🧪 Gist {i}",
            source="example.com",
            now=created,
        )
    for i in range(3):
        note = items.capture_note(db, f"🧪 note {i}", now=now - timedelta(hours=i))
        items.store_enrichment(db, note.id, sections=[lab.slug], title=f"🧪 Note {i}", now=now)
    items.edit_item(db, 1, status="done", now=now)
    overdue = items.capture_note(db, "🧪 overdue", now=now - timedelta(days=2))
    stored = items.store_enrichment(
        db, overdue.id, sections=[spare.slug], title="🧪 Overdue", now=now
    )
    reminders.fill_from_filing(
        db, stored, (now - timedelta(days=1)).replace(tzinfo=None), "UTC", now=now
    )


def seed_jobs(path: Path) -> None:
    """A few usage rows for the Usage tab; the server has already created the schema."""
    rows = [
        (TEST_ADMIN_ID, "admin", "pdf_tts", "🧪 a.pdf", "ok", 0.12, f"-{n} days") for n in range(4)
    ] + [(200, "invitee", "doc_translator", "🧪 b.docx", "ok", 0.31, "-1 days")]
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO jobs(telegram_id, username, agent, filename, status, cost_usd, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now', ?))",
            rows,
        )


def copy_db(src: Path, dst: Path) -> None:
    """A consistent copy through the sqlite backup API (the source may be in WAL mode)."""
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as a, sqlite3.connect(dst) as b:
        a.backup(b)


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex((HOST, port)) == 0


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/healthz", timeout=2) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None


def is_ours(pid: int) -> bool:
    """The PID still runs this launcher's server (a stale PID file may name a reused PID)."""
    cmd = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    return "telegram_bot.miniapp" in cmd.stdout


def stop(pid: int) -> None:
    """SIGTERM the server's process group, then SIGKILL if it lingers."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        for _ in range(50):
            if not pid_alive(pid):
                return
            time.sleep(0.1)


def up(args: argparse.Namespace) -> int:
    pid = read_pid()
    if pid is not None and pid_alive(pid):
        print(f"already running (pid {pid}); run `down` first", file=sys.stderr)
        return 1
    if port_busy(args.port):
        print(f"port {args.port} is taken", file=sys.stderr)
        return 1
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True, mode=0o700)
    try:
        return start(args)
    except BaseException:
        shutil.rmtree(WORK, ignore_errors=True)
        raise


def start(args: argparse.Namespace) -> int:
    """Copy or seed the DBs, start the server with a per-run key, write the signed URL."""
    if args.from_db_dir:
        source = Path(args.from_db_dir).expanduser()
        if not (source / SOURCE_NOTES).is_file():
            print(f"{source / SOURCE_NOTES} not found", file=sys.stderr)
            return 1
        copy_db(source / SOURCE_NOTES, NOTES_DB)
        if (source / SOURCE_BOT).is_file():
            copy_db(source / SOURCE_BOT, BOT_DB)
    else:
        seed_notes(NOTES_DB)
    for db in WORK.glob("*.sqlite3*"):
        db.chmod(0o600)

    # A random token per run: the signed URL is the only way in, and the real token never appears.
    secret = init_secret(f"42:{secrets.token_urlsafe(24)}")
    # Minimal env and a cwd without .env: the real token and keys never reach the server.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "ADMIN_TELEGRAM_ID": str(TEST_ADMIN_ID),
        "NOTES_DB_PATH": str(NOTES_DB),
        "TELEGRAM_DB_PATH": str(BOT_DB),
        "MINIAPP_INIT_SECRET": secret,
    }
    with LOG_FILE.open("wb") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "telegram_bot.miniapp",
                "--host",
                HOST,
                "--port",
                str(args.port),
            ],
            cwd=WORK,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    PID_FILE.write_text(f"{proc.pid}\n")

    deadline = time.monotonic() + 30
    while not healthy(args.port):
        if proc.poll() is not None or time.monotonic() > deadline:
            print(f"server did not become healthy; see {LOG_FILE}", file=sys.stderr)
            stop(proc.pid)
            shutil.rmtree(WORK, ignore_errors=True)
            return 1
        time.sleep(0.3)

    if not args.from_db_dir:
        seed_jobs(BOT_DB)
    URL_FILE.parent.mkdir(parents=True, exist_ok=True)
    URL_FILE.unlink(missing_ok=True)
    URL_FILE.touch(mode=0o600)
    URL_FILE.write_text(launch_url(args.port, secret) + "\n")
    print(f"port: {args.port}\nurl file: {URL_FILE}\npid file: {PID_FILE}")
    return 0


def down(_: argparse.Namespace) -> int:
    pid = read_pid()
    if pid is not None and pid_alive(pid) and is_ours(pid):
        stop(pid)
    shutil.rmtree(WORK, ignore_errors=True)
    URL_FILE.unlink(missing_ok=True)
    print("stopped; throwaway directory removed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_up = sub.add_parser("up", help="seed throwaway DBs, start the server, write the signed URL")
    p_up.add_argument(
        "--from-db-dir", metavar="DIR", help="copy notes.sqlite3 and telegram_bot.sqlite3 from DIR"
    )
    p_up.add_argument("--port", type=int, default=18083)
    p_up.set_defaults(func=up)
    p_down = sub.add_parser("down", help="stop the server and remove the throwaway directory")
    p_down.set_defaults(func=down)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
