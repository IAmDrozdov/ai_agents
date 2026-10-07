"""Consistent copies of both databases as a tar on stdout; `backup.py` feeds it to `python -` (ADR-018)."""

import hashlib
import io
import json
import os
import sqlite3
import sys
import tarfile

DATABASES = (
    ("notes.sqlite3", "NOTES_DB_PATH", "data/notes.sqlite3"),
    ("telegram_bot.sqlite3", "TELEGRAM_DB_PATH", "data/telegram_bot.sqlite3"),
)
MAX_BYTES = 100 * 2**20  # the copy is held in memory, inside the bot container's 700 MB cap


def snapshot(path: str) -> tuple[bytes, dict[str, int]]:
    """An online backup into memory, so the bot and the Mini App keep writing meanwhile."""
    if os.path.getsize(path) > MAX_BYTES:
        sys.exit(f"{path} is over {MAX_BYTES // 2**20} MB, too big for an in-memory copy")
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    mem = sqlite3.connect(":memory:")
    try:
        src.backup(mem)
    finally:
        src.close()
    tables = [
        row[0]
        for row in mem.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    counts = {t: mem.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
    data = mem.serialize()
    mem.close()
    return data, counts


def add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def main() -> None:
    meta: dict[str, dict[str, object]] = {}
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|") as tar:
        for name, env, default in DATABASES:
            path = os.environ.get(env, default)
            try:
                data, counts = snapshot(path)
            except OSError as e:
                sys.exit(f"{path}: {e.strerror or e}")
            except sqlite3.Error as e:
                sys.exit(f"{path}: {e}")
            meta[name] = {
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "row_counts": counts,
            }
            add(tar, name, data)
        add(tar, "meta.json", json.dumps(meta).encode())


if __name__ == "__main__":
    main()
