"""sqlite persistence for the Telegram bot: users, invites, settings, usage.

All helpers are synchronous; async callers wrap them in ``asyncio.to_thread``.
Connections are opened per call (WAL mode), which is thread-safe by construction
and lets the Mini App read while the bot writes.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from shared.config import settings

INVITE_TTL_HOURS = 48

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id  INTEGER PRIMARY KEY,
    username     TEXT,
    first_name   TEXT,
    invite_token TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS invites (
    token      TEXT PRIMARY KEY,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    used_by    INTEGER,
    used_at    TEXT
);

CREATE TABLE IF NOT EXISTS user_settings (
    telegram_id INTEGER NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (telegram_id, key)
);

CREATE TABLE IF NOT EXISTS jobs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id         INTEGER NOT NULL,
    username            TEXT,
    agent               TEXT NOT NULL,
    filename            TEXT,
    file_size_bytes     INTEGER,
    output_size_bytes   INTEGER,
    char_count          INTEGER,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    tts_chars_billed    INTEGER,
    cost_usd            REAL,
    estimated_cost_usd  REAL,
    duration_s          REAL,
    status              TEXT NOT NULL,
    error               TEXT,
    config_json         TEXT,
    stats_json          TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(telegram_id);
"""


def _db_path() -> str:
    return settings.telegram_db_path


def _connect(*, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, timeout=5)
    else:
        conn = sqlite3.connect(_db_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    Path(_db_path()).parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        with contextlib.suppress(sqlite3.OperationalError):  # column already migrated
            conn.execute("ALTER TABLE jobs ADD COLUMN estimated_cost_usd REAL")


def reconcile_running_jobs() -> int:
    """Close out jobs a previous process left mid-flight. Returns how many.

    Falls back to the approved estimate for cost_usd (rather than leaving it NULL,
    counted as $0 by the daily cap) — see the security review, M4.
    """
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status='interrupted', finished_at=datetime('now'), "
            "error='interrupted by a restart', "
            "cost_usd=COALESCE(cost_usd, estimated_cost_usd) WHERE status='running'"
        )
        return int(cur.rowcount or 0)


# --- users / invites -------------------------------------------------------


def upsert_user(
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    invite_token: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO users(telegram_id, username, first_name, invite_token) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username, "
            "first_name=excluded.first_name",
            (telegram_id, username, first_name, invite_token),
        )


def is_whitelisted(telegram_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM users WHERE telegram_id=?", (telegram_id,)).fetchone()
    return row is not None


def list_users() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT telegram_id, username, first_name, created_at FROM users ORDER BY created_at"
        ).fetchall()
    return [dict(row) for row in rows]


def delete_user(telegram_id: int) -> bool:
    """Drop a user and their settings; True if there was a user row to drop."""
    with _connect() as conn:
        conn.execute("DELETE FROM user_settings WHERE telegram_id=?", (telegram_id,))
        cur = conn.execute("DELETE FROM users WHERE telegram_id=?", (telegram_id,))
        return cur.rowcount == 1


def create_invite(token: str, created_by: int) -> None:
    with _connect() as conn:
        conn.execute("INSERT INTO invites(token, created_by) VALUES (?, ?)", (token, created_by))


def redeem_invite(
    token: str, telegram_id: int, username: str | None, first_name: str | None
) -> bool:
    """Atomically consume a one-time invite; True if this call redeemed it.

    An unredeemed link stops working after INVITE_TTL_HOURS so a leaked one is not
    a standing credential.
    """
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE invites SET used_by=?, used_at=datetime('now') "
            "WHERE token=? AND used_by IS NULL AND created_at > datetime('now', ?)",
            (telegram_id, token, f"-{INVITE_TTL_HOURS} hours"),
        )
        if cur.rowcount != 1:
            return False
        conn.execute(
            "INSERT OR IGNORE INTO users(telegram_id, username, first_name, invite_token) "
            "VALUES (?, ?, ?, ?)",
            (telegram_id, username, first_name, token),
        )
        return True


# --- per-user settings -----------------------------------------------------


def get_user_settings(telegram_id: int) -> dict[str, str]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT key, value FROM user_settings WHERE telegram_id=?", (telegram_id,)
        ).fetchall()
    return {row["key"]: row["value"] for row in rows}


def set_user_setting(telegram_id: int, key: str, value: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO user_settings(telegram_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(telegram_id, key) DO UPDATE SET value=excluded.value, "
            "updated_at=datetime('now')",
            (telegram_id, key, value),
        )


# --- usage log -------------------------------------------------------------


def insert_job(
    telegram_id: int,
    username: str | None,
    agent: str,
    filename: str,
    file_size_bytes: int,
    config_json: dict[str, Any],
    estimated_cost_usd: float = 0.0,
) -> int:
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO jobs(telegram_id, username, agent, filename, file_size_bytes, "
            "status, config_json, estimated_cost_usd) VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
            (
                telegram_id,
                username,
                agent,
                filename,
                file_size_bytes,
                json.dumps(config_json, ensure_ascii=False, default=str),
                estimated_cost_usd,
            ),
        )
        return int(cur.lastrowid or 0)


def finish_job(
    job_id: int,
    status: str,
    *,
    error: str | None = None,
    cost_usd: float | None = None,
    char_count: int | None = None,
    stats: dict[str, Any] | None = None,
    duration_s: float | None = None,
    output_size_bytes: int | None = None,
) -> None:
    # input_tokens / output_tokens / tts_chars_billed columns stay in the schema for old
    # rows and the usage view, but are no longer written; stats_json carries cost lines.
    with _connect() as conn:
        conn.execute(
            "UPDATE jobs SET status=?, error=?, stats_json=?, cost_usd=?, char_count=?, "
            "duration_s=?, output_size_bytes=?, finished_at=datetime('now') WHERE id=?",
            (
                status,
                error,
                json.dumps(stats or {}, ensure_ascii=False, default=str),
                cost_usd,
                char_count,
                duration_s,
                output_size_bytes,
                job_id,
            ),
        )


def user_cost_since(telegram_id: int, hours: int) -> float:
    """Total recorded cost for one user over the last `hours`. Fuels the spend cap."""
    with _connect(readonly=True) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) AS spent FROM jobs "
            "WHERE telegram_id=? AND created_at > datetime('now', ?)",
            (telegram_id, f"-{int(hours)} hours"),
        ).fetchone()
    return float(row["spent"]) if row else 0.0


# --- ETA samples -----------------------------------------------------------


def recent_job_samples(agent: str, limit: int = 30) -> list[dict[str, Any]]:
    """Recent ok jobs with timing + size, newest first — fuels the ETA predictor."""
    with _connect(readonly=True) as conn:
        rows = conn.execute(
            "SELECT char_count, duration_s, config_json FROM jobs "
            "WHERE agent=? AND status='ok' AND duration_s > 0 AND char_count > 0 "
            "ORDER BY id DESC LIMIT ?",
            (agent, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        raw = item.get("config_json")
        try:
            item["config_json"] = json.loads(raw) if raw else None
        except ValueError:
            item["config_json"] = None
        out.append(item)
    return out


# --- usage queries (Mini App) -----------------------------------------------------


def query_history(limit: int = 200) -> list[dict[str, Any]]:
    with _connect(readonly=True) as conn:
        rows = conn.execute(
            "SELECT id, telegram_id, username, agent, filename, file_size_bytes, "
            "output_size_bytes, char_count, input_tokens, output_tokens, "
            "tts_chars_billed, cost_usd, duration_s, status, error, created_at, "
            "finished_at, config_json, stats_json FROM jobs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        for key in ("config_json", "stats_json"):
            try:
                item[key] = json.loads(item[key]) if item[key] else None
            except ValueError:
                item[key] = None
        out.append(item)
    return out


def query_by_user() -> list[dict[str, Any]]:
    with _connect(readonly=True) as conn:
        rows = conn.execute(
            "SELECT telegram_id, MAX(username) AS username, COUNT(*) AS jobs, "
            "SUM(COALESCE(char_count, 0)) AS chars, "
            "SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) AS tokens, "
            "ROUND(SUM(COALESCE(cost_usd, 0)), 4) AS cost_usd "
            "FROM jobs GROUP BY telegram_id ORDER BY cost_usd DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def query_by_user_agent() -> list[dict[str, Any]]:
    with _connect(readonly=True) as conn:
        rows = conn.execute(
            "SELECT telegram_id, MAX(username) AS username, agent, COUNT(*) AS jobs, "
            "SUM(COALESCE(char_count, 0)) AS chars, "
            "SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)) AS tokens, "
            "ROUND(SUM(COALESCE(cost_usd, 0)), 4) AS cost_usd "
            "FROM jobs GROUP BY telegram_id, agent ORDER BY telegram_id, agent"
        ).fetchall()
    return [dict(row) for row in rows]


def query_daily_cost(days: int) -> list[dict[str, Any]]:
    """Cost per UTC day over the last `days` days, today included; days without jobs are absent."""
    with _connect(readonly=True) as conn:
        rows = conn.execute(
            "SELECT date(created_at) AS day, ROUND(SUM(COALESCE(cost_usd, 0)), 4) AS cost_usd "
            "FROM jobs WHERE created_at >= date('now', ?) GROUP BY day ORDER BY day",
            (f"-{int(days) - 1} days",),
        ).fetchall()
    return [dict(row) for row in rows]


def query_totals() -> dict[str, Any]:
    with _connect(readonly=True) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS jobs, "
            "SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok_jobs, "
            "SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS error_jobs, "
            "ROUND(SUM(COALESCE(cost_usd, 0)), 4) AS cost_usd "
            "FROM jobs"
        ).fetchone()
    return dict(row) if row else {}
