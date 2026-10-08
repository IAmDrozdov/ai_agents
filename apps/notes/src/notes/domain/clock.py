"""The Owner's clock: stored UTC stamps, the Owner's Zone, and the conversions between them (ADR-0011)."""

from __future__ import annotations

from datetime import UTC, date, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from notes.db import Database

_FORMAT = "%Y-%m-%d %H:%M:%S"  # sqlite's own datetime('now') text; private on purpose
ZONE_KEY = "zone"
DEFAULT_ZONE = "UTC"
WEEKDAYS_RU = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def stamp(now: datetime | None = None) -> str:
    """A moment (default: now) as the UTC text the store keeps, so comparisons stay textual."""
    return (now or datetime.now(UTC)).astimezone(UTC).strftime(_FORMAT)


def parse(stamped: str) -> datetime:
    """A stored stamp as an aware UTC moment; ValueError on text that is not a stamp."""
    return datetime.strptime(stamped, _FORMAT).replace(tzinfo=UTC)


def iso(stamped: str) -> str:
    """A stored stamp as `2026-10-10T19:00:00Z`, the form the Mini App reads a Due in."""
    return parse(stamped).isoformat().replace("+00:00", "Z")


def is_zone(name: str) -> bool:
    """Whether `name` is a real IANA zone."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def zone(name: str) -> tzinfo:
    """The named IANA zone, or UTC when it is unknown (never raises)."""
    return ZoneInfo(name) if is_zone(name) else UTC


def local(stamped: str, tz: str) -> datetime:
    """A stored stamp as an aware moment in zone `tz` (UTC when `tz` is unknown)."""
    return parse(stamped).astimezone(zone(tz))


def local_to_utc(local: datetime, tz: str) -> datetime:
    """A naive wall-clock moment in zone `tz` as an aware UTC moment (the Classifier's Due)."""
    return local.replace(tzinfo=zone(tz)).astimezone(UTC)


def local_clock(moment: datetime, tz: str) -> str:
    """The moment as the Classifier is told it: «2026-10-07 20:58, среда» in `tz`; a naive moment is already in `tz`."""
    shown = moment.astimezone(zone(tz)) if moment.tzinfo is not None else moment
    return f"{shown:%Y-%m-%d %H:%M}, {WEEKDAYS_RU[shown.weekday()]}"


def local_day(stamped: str, tz: str) -> date:
    """The Owner's calendar day a stored stamp falls on (Dashboard heatmaps)."""
    return local(stamped, tz).date()


def local_midnight_utc(day: date, tz: str) -> str:
    """The stamp at which `day` starts in zone `tz` (day windows in SQL)."""
    return stamp(datetime(day.year, day.month, day.day, tzinfo=zone(tz)))


def owner_zone(db: Database) -> str:
    """The Owner's Zone as the Mini App last reported it; `DEFAULT_ZONE` until it first opens."""
    with db.session(readonly=True) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (ZONE_KEY,)).fetchone()
    return row["value"] if row else DEFAULT_ZONE


def remember_zone(db: Database, name: str) -> None:
    """Keep `name` as the Owner's Zone when it is a real IANA zone and differs from the stored one."""
    if not is_zone(name) or name == owner_zone(db):
        return
    with db.session() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (ZONE_KEY, name),
        )
