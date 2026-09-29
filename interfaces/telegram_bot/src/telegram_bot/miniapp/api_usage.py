"""Usage endpoint: the bot's totals, per-user spend and job history (ADR-016)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from .. import db
from .auth import require_admin

router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])

DAILY_DAYS = 14  # the sparkline's span; static/usage.js draws the same number of days


@router.get("/usage")
def usage(limit: int = Query(200, ge=1, le=1000)) -> dict[str, Any]:
    return {
        "totals": db.query_totals(),
        "by_user": db.query_by_user(),
        "daily": db.query_daily_cost(DAILY_DAYS),
        "jobs": db.query_history(limit),
        "generated_at": datetime.now(UTC).isoformat(),
    }
