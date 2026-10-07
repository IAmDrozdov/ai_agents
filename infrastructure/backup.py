"""Daily Backup of the bot's data to the Owner's Mac (ADR-018); see infrastructure/README.md "Backups"."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import http.client
import io
import json
import logging
import mimetypes
import os
import plistlib
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PROGRAM = REPO_ROOT / "infrastructure" / "backup_snapshot.py"
GATE = REPO_ROOT / "infrastructure" / "ssh-gate.sh"
COMPOSE = "docker compose -f /opt/ai_agents/src/infrastructure/docker/docker-compose.yml"
DATABASES = ("notes.sqlite3", "telegram_bot.sqlite3")

HOME = Path.home()
ICLOUD_DRIVE = HOME / "Library/Mobile Documents/com~apple~CloudDocs"
DEFAULT_BACKUP_DIR = ICLOUD_DRIVE / "Backups/ai-agents"
STAGING_ROOT = HOME / "Library/Caches/ai-agents-backup"
STATE_DIR = HOME / "Library/Application Support/ai-agents-backup"
LOG_PATH = HOME / "Library/Logs/ai-agents-backup.log"
LABEL = "local.ai-agents.backup"
PLIST_PATH = HOME / "Library/LaunchAgents" / f"{LABEL}.plist"

KEEP_DAYS = 30
MAX_DOWNLOAD = 20 * 1024 * 1024  # the Bot API's getFile limit
STALE_AFTER = timedelta(hours=48)
ALERT_EVERY = timedelta(hours=24)
SNAPSHOT_TIMEOUT_S = 600
# Per connect and per read: urllib tries a dead IPv6 route first, up to this long, then IPv4.
HTTP_TIMEOUT_S = 20
# A day folder; `-HHMMSS` marks an earlier Backup of that day that a forced run moved aside.
DAY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(-\d{6})?$")
# `<item id>-<file_id hash>-`: ids come back after a restore, so the id alone is not the file.
FILE_RE = re.compile(r"^(\d+-[0-9a-f]{8})-")
NETWORK_ERRORS = (urllib.error.URLError, http.client.HTTPException, OSError, ValueError)

log = logging.getLogger("backup")


class BackupError(Exception):
    """A run cannot produce a verified Backup; the message is the alert's reason."""


class BotApiError(Exception):
    """A Bot API call failed; the message never contains the URL (it holds the token)."""


def now() -> datetime:
    return datetime.now().astimezone()


def read_env(*keys: str) -> dict[str, str]:
    """The named keys from the repo's `.env`, last one wins, quotes stripped as ssh-gate.sh does."""
    path = REPO_ROOT / ".env"
    found: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key in keys:
                found[key] = re.sub(r"^['\"]|['\"]$", "", value.strip())
    return {k: v for k, v in found.items() if v}


class Redacting(logging.Formatter):
    def __init__(self, secret: str | None) -> None:
        super().__init__("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
        self.secret = secret

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        return text.replace(self.secret, "<token>") if self.secret else text


def setup_logging(secret: str | None) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH)]
    # Under launchd stderr already is the log file; a second handler would double every line.
    if not (LOG_PATH.exists() and os.path.samestat(os.fstat(2), os.stat(LOG_PATH))):
        handlers.append(logging.StreamHandler())
    for handler in handlers:
        handler.setFormatter(Redacting(secret))
        log.addHandler(handler)
    log.setLevel(logging.INFO)


# --- Bot API -------------------------------------------------------------------------------


def why(e: BaseException) -> str:
    return str(getattr(e, "reason", None) or e) or type(e).__name__


def bot_api(token: str, method: str, **params: object) -> dict[str, Any]:
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)  # Telegram explains a refusal in the body
        except NETWORK_ERRORS:
            raise BotApiError(f"{method}: HTTP {e.code}") from None
    except NETWORK_ERRORS as e:
        raise BotApiError(f"{method}: {why(e)}") from None
    if not isinstance(body, dict) or not body.get("ok"):
        description = body.get("description") if isinstance(body, dict) else None
        raise BotApiError(str(description or f"{method}: not ok"))
    return body["result"]


def download(token: str, tg_path: str, dest: Path, size: int | None) -> None:
    """Fetch one file; a short read raises, since urllib ends a cut-off body without an error."""
    url = f"https://api.telegram.org/file/bot{token}/{urllib.parse.quote(tg_path)}"
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as resp, dest.open("wb") as out:
            expected = size or int(resp.headers.get("Content-Length") or 0)
            shutil.copyfileobj(resp, out)
            got = out.tell()
    except urllib.error.HTTPError as e:
        raise BotApiError(f"download: HTTP {e.code}") from None
    except NETWORK_ERRORS as e:
        raise BotApiError(f"download: {why(e)}") from None
    if expected and got != expected:
        raise BotApiError(f"download: got {got} of {expected} bytes")


# --- Alerts --------------------------------------------------------------------------------


def state_path(source: str) -> Path:
    # A local check's success must never count as a real Backup.
    return STATE_DIR / ("state.json" if source == "droplet" else f"state-{source}.json")


def load_state(source: str) -> dict[str, Any]:
    cutoff = now() - ALERT_EVERY
    try:
        state = json.loads(state_path(source).read_text())
        alerts = state.get("alerts", {})
        state["alerts"] = {k: t for k, t in alerts.items() if datetime.fromisoformat(t) > cutoff}
        if state.get("last_success"):
            datetime.fromisoformat(state["last_success"])
    except (OSError, ValueError, TypeError, AttributeError):
        state = {"alerts": {}}
    return state


def save_state(source: str, state: dict[str, Any]) -> None:
    path = state_path(source)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    os.replace(tmp, path)


class Alerts:
    """A macOS banner plus a bot message, at most once per 24 h per reason."""

    def __init__(self, source: str, state: dict[str, Any], env: dict[str, str]) -> None:
        self.source = source
        self.state = state
        self.token = env.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = env.get("ADMIN_TELEGRAM_ID")

    def send(self, reason: str, text: str) -> None:
        if self.token:
            text = text.replace(self.token, "<token>")
        if reason in self.state["alerts"]:
            log.info("alert held back, already sent within 24 h: %s", text)
            return
        log.warning("alert: %s", text)
        banner(text)
        if self.source == "local":
            log.info("would send: %s", text)
        elif not (self.token and self.chat_id):
            log.error("no bot message: TELEGRAM_BOT_TOKEN or ADMIN_TELEGRAM_ID missing in .env")
        else:
            try:
                sent = bot_api(self.token, "sendMessage", chat_id=self.chat_id, text=text)
                log.info("bot message sent, message_id %s", sent.get("message_id"))
            except BotApiError as e:
                log.error("bot message failed, the next run tries again: %s", e)
                return
        self.state["alerts"][reason] = now().isoformat(timespec="seconds")
        save_state(self.source, self.state)


def banner(text: str) -> None:
    script = (
        'on run argv\ndisplay notification (item 1 of argv) with title "ai_agents backup"\nend run'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script, text], capture_output=True, timeout=15, check=True
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.error("banner failed: %s", e)


# --- Snapshot and verification -------------------------------------------------------------


def last_line(raw: bytes) -> str:
    lines = [ln.strip() for ln in raw.decode(errors="replace").splitlines() if ln.strip()]
    return lines[-1] if lines else "no output"


def take_snapshot(source: str) -> bytes:
    """Run the snapshot program where the databases are and return its tar stream."""
    if source == "local":
        cmd = [sys.executable, "-"]
    else:  # a one-off bot container as `app`, never root on the host; works while the bot is down
        cmd = [str(GATE), "ssh", f"{COMPOSE} run --rm --no-deps -T bot python -"]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO_ROOT,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(SNAPSHOT_PROGRAM.read_bytes(), timeout=SNAPSHOT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # TERM to the whole group: ssh exits and the gate's trap closes port 22.
        os.killpg(proc.pid, signal.SIGTERM)
        proc.communicate(timeout=60)
        raise BackupError(f"snapshot timed out after {SNAPSHOT_TIMEOUT_S} s") from None
    for line in err.decode(errors="replace").splitlines():
        if line.strip():
            log.info("  %s", line.strip())
    if proc.returncode != 0:
        raise BackupError(f"snapshot exited {proc.returncode}: {last_line(err)}")
    return out


def unpack(stream: bytes, day: Path) -> dict[str, Any]:
    members: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(stream), mode="r:") as tar:
            for member in tar:
                f = tar.extractfile(member) if member.isfile() else None
                if f is not None:
                    members[member.name] = f.read()
    except tarfile.TarError as e:
        raise BackupError(f"snapshot stream is not a tar: {e}") from None
    if "meta.json" not in members or any(name not in members for name in DATABASES):
        raise BackupError(f"snapshot stream is incomplete: {sorted(members)}")
    for name in DATABASES:
        (day / name).write_bytes(members[name])
    return json.loads(members["meta.json"])


def open_copy(data: bytes) -> sqlite3.Connection:
    """The copy in memory; bytes 18-19 are set to rollback, since a WAL image cannot load."""
    image = bytearray(data)
    image[18:20] = b"\x01\x01"
    conn = sqlite3.connect(":memory:")
    conn.deserialize(bytes(image))
    return conn


def verify(day: Path, meta: dict[str, Any]) -> tuple[dict[str, Any], sqlite3.Connection]:
    """Checksum, integrity and row counts of each staged copy; returns the manifest entries."""
    entries: dict[str, Any] = {}
    notes: sqlite3.Connection | None = None
    for name in DATABASES:
        data = (day / name).read_bytes()
        expected = meta[name]
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected["sha256"] or len(data) != expected["size"]:
            raise BackupError(f"{name}: checksum or size differs from the snapshot")
        try:
            conn = open_copy(data)
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            counts = {
                t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                for t in expected["row_counts"]
            }
        except sqlite3.Error as e:
            raise BackupError(f"{name}: not a readable database ({e})") from None
        if integrity != "ok":
            raise BackupError(f"{name}: integrity_check says {integrity}")
        if counts != expected["row_counts"]:
            raise BackupError(f"{name}: row counts differ from the snapshot")
        entries[name] = {
            "sha256": digest,
            "size": len(data),
            "integrity_check": integrity,
            "row_counts": counts,
        }
        if name == "notes.sqlite3":
            notes = conn
        else:
            conn.close()
    assert notes is not None
    return entries, notes


# --- Bytes of Files and Voices -------------------------------------------------------------


def file_key(item_id: int, file_id: str) -> str:
    return f"{item_id}-{hashlib.sha256(file_id.encode()).hexdigest()[:8]}"


def file_name_for(
    key: str, kind: str, file_name: str | None, file_mime: str | None, tg_path: str
) -> str:
    """`<key>-<sanitised name or kind>.<ext>`; the extension from Telegram's path, else the mime."""
    ext = PurePosixPath(tg_path).suffix or (PurePosixPath(file_name).suffix if file_name else "")
    if not ext and file_mime:
        ext = mimetypes.guess_extension(file_mime) or ""
    stem = PurePosixPath(file_name).stem if file_name else kind
    stem = re.sub(r"[^\w.-]+", "_", stem).strip("._")[:80] or kind
    return f"{key}-{stem}{re.sub(r'[^A-Za-z0-9.]', '', ext)[:10]}"


def fetch_files(
    notes: sqlite3.Connection, files_dir: Path, work: Path, token: str | None
) -> dict[str, Any]:
    """Download the bytes not on disk yet; returns the manifest's file fields."""
    rows = notes.execute(
        "SELECT id, kind, file_id, file_name, file_mime, file_size FROM items "
        "WHERE file_id IS NOT NULL ORDER BY id"
    ).fetchall()
    on_disk: set[str] = set()
    if files_dir.is_dir():
        on_disk = {m[1] for p in files_dir.iterdir() if (m := FILE_RE.match(p.name))}
    downloaded: list[int] = []
    missing: list[dict[str, Any]] = []
    for item_id, kind, file_id, file_name, file_mime, file_size in rows:
        key = file_key(item_id, file_id)
        if key in on_disk:
            continue
        if file_size and file_size > MAX_DOWNLOAD:
            missing.append({"item_id": item_id, "reason": "too_big"})
            continue
        try:
            if not token:
                raise BotApiError("TELEGRAM_BOT_TOKEN is not set in .env")
            info = bot_api(token, "getFile", file_id=file_id)
            tg_path = info.get("file_path")
            if not tg_path:
                raise BotApiError("getFile returned no file_path")
            name = file_name_for(key, kind, file_name, file_mime, tg_path)
            download(token, tg_path, work / name, info.get("file_size"))
            files_dir.mkdir(parents=True, exist_ok=True)
            os.replace(work / name, files_dir / name)
        except BotApiError as e:
            reason = "too_big" if "too big" in str(e) else str(e)
            missing.append({"item_id": item_id, "reason": reason})
            if reason != "too_big":
                log.warning("item %s: %s", item_id, reason)
            continue
        downloaded.append(item_id)
        log.info("item %s: saved files/%s", item_id, name)
    return {
        "file_item_ids": [row[0] for row in rows],
        "file_keys": [file_key(row[0], row[2]) for row in rows],
        "downloaded": downloaded,
        "missing": missing,
    }


# --- Placing and retention -----------------------------------------------------------------


def staging_root_for(backup_dir: Path) -> Path:
    """The cache dir when it shares a volume with the Backup dir, so the final move is a rename."""
    STAGING_ROOT.mkdir(parents=True, exist_ok=True)
    if os.stat(STAGING_ROOT).st_dev == os.stat(backup_dir).st_dev:
        return STAGING_ROOT
    return backup_dir / ".staging"


def place(day: Path, target: Path) -> None:
    """Move the verified day folder in with one rename; an earlier one of that day is kept aside."""
    if target.exists():
        made = datetime.fromtimestamp((target / "manifest.json").stat().st_mtime)
        aside = target.with_name(f"{target.name}-{made:%H%M%S}")
        while aside.exists():  # two forced runs within a second
            made += timedelta(seconds=1)
            aside = target.with_name(f"{target.name}-{made:%H%M%S}")
        os.rename(target, aside)
        log.info("earlier Backup of today kept as %s", aside.name)
    os.rename(day, target)


def prune(backup_dir: Path) -> None:
    """Keep the folders of the newest days, and the files that a kept manifest still lists."""
    folders = {p: m[1] for p in backup_dir.iterdir() if p.is_dir() and (m := DAY_RE.match(p.name))}
    kept_days = sorted(set(folders.values()), reverse=True)[:KEEP_DAYS]
    keep: set[str] = set()
    for folder, day in sorted(folders.items(), reverse=True):
        if day not in kept_days:
            shutil.rmtree(folder)
            log.info("pruned %s", folder.name)
            continue
        try:
            keep.update(json.loads((folder / "manifest.json").read_text())["file_keys"])
        except (OSError, ValueError, KeyError) as e:
            log.warning("files left as they are: cannot read %s/manifest.json (%s)", folder.name, e)
            return
    files_dir = backup_dir / "files"
    if files_dir.is_dir():
        for f in sorted(files_dir.iterdir()):
            m = FILE_RE.match(f.name)
            if m and m[1] not in keep:
                f.unlink()
                log.info("pruned files/%s", f.name)


# --- Commands ------------------------------------------------------------------------------


def make_backup(source: str, backup_dir: Path, today: str, token: str | None) -> dict[str, Any]:
    if backup_dir == DEFAULT_BACKUP_DIR and not ICLOUD_DRIVE.is_dir():
        # Creating the path would leave Backups on this disk only, which ADR-018 exists to avoid.
        raise BackupError("iCloud Drive is not available (signed out or turned off)")
    backup_dir.mkdir(parents=True, exist_ok=True)
    staging = staging_root_for(backup_dir)
    shutil.rmtree(staging, ignore_errors=True)  # leftovers of a killed run; the lock is ours
    work = staging / f"{today}.{os.getpid()}"
    day = work / today
    day.mkdir(parents=True)
    try:
        meta = unpack(take_snapshot(source), day)
        databases, notes = verify(day, meta)
        log.info("databases verified: %s", {n: e["row_counts"] for n, e in databases.items()})
        try:
            files = fetch_files(notes, backup_dir / "files", work, token)
        finally:
            notes.close()
        manifest = {
            "created_at": now().isoformat(timespec="seconds"),
            "source": source,
            "databases": databases,
            **files,
        }
        (day / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        )
        place(day, backup_dir / today)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def check_gate_closed() -> None:
    """Log, never raise: the Backup is already placed and its result must stand."""
    try:
        proc = subprocess.run(
            [str(GATE), "status"], capture_output=True, cwd=REPO_ROOT, timeout=120
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("could not check ssh-gate status: %s", e)
        return
    if proc.returncode != 0:
        log.warning("could not check ssh-gate status: %s", last_line(proc.stderr))
    elif proc.stdout.strip() != b"closed":
        log.warning("ssh-gate status is not 'closed' after the run (another gate holder?)")


def report_failure(alerts: Alerts, reason: str) -> None:
    """Alert from the second failure in a row, or at once when no good Backup is 48 h old."""
    state = alerts.state
    state["failures"] = state.get("failures", 0) + 1
    save_state(alerts.source, state)
    last = state.get("last_success")
    if state["failures"] < 2 and last and now() - datetime.fromisoformat(last) <= STALE_AFTER:
        log.info("first failure in a row; the next run alerts if it fails too")
        return
    since = f" (last good Backup {last[:16].replace('T', ' ')})" if last else ""
    alerts.send(f"failed: {reason}", f"⚠️ ai_agents backup failed: {reason}{since}")


def run(source: str, force: bool) -> int:
    env = read_env("TELEGRAM_BOT_TOKEN", "ADMIN_TELEGRAM_ID")
    token = env.get("TELEGRAM_BOT_TOKEN")
    setup_logging(token)
    override = os.environ.get("AI_AGENTS_BACKUP_DIR")
    if source == "local" and not override:
        log.error(
            "--source local needs AI_AGENTS_BACKUP_DIR (a scratch dir), never the real Backups"
        )
        return 2
    backup_dir = Path(override).expanduser() if override else DEFAULT_BACKUP_DIR
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with (STATE_DIR / "run.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if not force:
                log.info("another run is in progress; nothing to do")
                return 0
            log.info("waiting for the run in progress")
            fcntl.flock(lock, fcntl.LOCK_EX)
        today = date.today().isoformat()
        if (backup_dir / today / "manifest.json").exists() and not force:
            log.info("today's Backup %s exists; nothing to do", today)
            return 0
        state = load_state(source)
        alerts = Alerts(source, state, env)
        log.info("run: source=%s force=%s dir=%s", source, force, backup_dir)
        try:
            manifest = make_backup(source, backup_dir, today, token)
        except BackupError as e:
            log.error("run failed: %s", e)
            report_failure(alerts, str(e))
            return 1
        except Exception as e:
            log.exception("run failed")
            report_failure(alerts, f"{type(e).__name__}: {e}")
            return 1
        finally:
            if source == "droplet":
                check_gate_closed()
        state["last_success"] = manifest["created_at"]
        state["failures"] = 0
        save_state(source, state)
        failed = [m for m in manifest["missing"] if m["reason"] != "too_big"]
        too_big = len(manifest["missing"]) - len(failed)
        log.info(
            "Backup %s placed: %d file items, %d downloaded, %d too big, %d failed",
            today,
            len(manifest["file_item_ids"]),
            len(manifest["downloaded"]),
            too_big,
            len(failed),
        )
        if failed:
            alerts.send(
                "warning",
                f"⚠️ ai_agents backup: {len(failed)} file(s) could not be fetched, see {today}/manifest.json",
            )
        try:
            prune(backup_dir)
        except OSError as e:
            log.warning("retention skipped: %s", e)
        return 0


def install() -> int:
    """Write the LaunchAgent for this machine and load it; nothing machine-specific is committed."""
    tools = {name: shutil.which(name) for name in ("python3", "terraform", "ssh", "curl")}
    if not all(tools.values()):
        print(f"not found on PATH: {[n for n, p in tools.items() if not p]}", file=sys.stderr)
        return 1
    dirs = [str(Path(p).parent) for p in tools.values() if p]
    path = ":".join(dict.fromkeys([*dirs, "/usr/bin", "/bin", "/usr/sbin", "/sbin"]))
    env = {"PATH": path}
    for key in ("SSH_KEY", "AI_AGENTS_BACKUP_DIR"):
        if os.environ.get(key):
            env[key] = str(Path(os.environ[key]).expanduser())
    if "SSH_KEY" not in env:
        print("warning: SSH_KEY is not set, so ssh uses its default key", file=sys.stderr)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(Path(__file__).resolve()), "run"],
        "WorkingDirectory": str(REPO_ROOT),
        "EnvironmentVariables": env,
        "StartInterval": 3600,
        "RunAtLoad": True,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
    }
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PLIST_PATH.open("wb") as f:
        plistlib.dump(plist, f)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)
    for _ in range(50):  # bootout returns before the old job is gone; bootstrap would fail with 5
        gone = subprocess.run(["launchctl", "print", f"{domain}/{LABEL}"], capture_output=True)
        if gone.returncode != 0:
            break
        time.sleep(0.2)
    subprocess.run(["launchctl", "bootstrap", domain, str(PLIST_PATH)], check=True)
    print(f"installed {LABEL}: hourly and at login; log {LOG_PATH}")
    return 0


def uninstall() -> int:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    PLIST_PATH.unlink(missing_ok=True)
    print(f"removed {LABEL}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="make today's Backup unless it exists")
    run_p.add_argument("--force", action="store_true", help="replace today's Backup")
    run_p.add_argument(
        "--source",
        choices=("droplet", "local"),
        default="droplet",
        help="local: the local databases into AI_AGENTS_BACKUP_DIR, no bot messages",
    )
    sub.add_parser("install", help="run hourly and at login through launchd")
    sub.add_parser("uninstall", help="remove the launchd agent")
    args = parser.parse_args()
    if args.command == "run":
        return run(args.source, args.force)
    return install() if args.command == "install" else uninstall()


if __name__ == "__main__":
    sys.exit(main())
