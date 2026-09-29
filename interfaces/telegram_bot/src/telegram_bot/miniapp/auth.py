"""Mini App auth: verify Telegram-signed initData and admit only the admin (ADR-016)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request

from shared.config import settings
from shared.obs import get_logger

log = get_logger(__name__)

MAX_AGE_S = 24 * 3600
CLOCK_SKEW_S = 60


class InitDataError(ValueError):
    """The initData is forged, stale or malformed."""


def init_secret() -> bytes:
    """The initData HMAC key: the deployed derived key, else derived from TELEGRAM_BOT_TOKEN."""
    configured = settings.miniapp_init_secret
    if configured is not None and configured.get_secret_value():
        try:
            key = bytes.fromhex(configured.get_secret_value())
        except ValueError:
            key = b""
        if len(key) != 32:
            raise RuntimeError("MINIAPP_INIT_SECRET must be 64 hex characters")
        return key
    token = settings.telegram_bot_token
    if token is not None and token.get_secret_value():
        return hmac.new(b"WebAppData", token.get_secret_value().encode(), hashlib.sha256).digest()
    raise RuntimeError("set MINIAPP_INIT_SECRET or TELEGRAM_BOT_TOKEN")


def verify_init_data(init_data: str, secret: bytes, *, now: float | None = None) -> dict[str, Any]:
    """The Telegram user from signed initData; raises InitDataError when forged, stale or incomplete."""
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise InitDataError("malformed initData") from exc
    received = fields.pop("hash", "")
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected.encode(), received.encode()):
        raise InitDataError("bad signature")
    try:
        age = (time.time() if now is None else now) - int(fields["auth_date"])
        user = json.loads(fields["user"])
    except (KeyError, ValueError) as exc:
        raise InitDataError("missing auth_date or user") from exc
    if not -CLOCK_SKEW_S <= age <= MAX_AGE_S:
        raise InitDataError("stale initData")
    if not isinstance(user, dict):
        raise InitDataError("bad user")
    return user


def require_admin(request: Request) -> int:
    """FastAPI dependency: 401 without valid initData, 403 for anyone but ADMIN_TELEGRAM_ID."""
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "tma" or not credentials:
        raise HTTPException(status_code=401, detail="Telegram initData required")
    try:
        user = verify_init_data(credentials, request.app.state.init_secret)
    except InitDataError as exc:
        log.info("miniapp auth rejected: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired initData") from exc
    user_id = user.get("id")
    if type(user_id) is not int or user_id != settings.admin_telegram_id:
        log.info("miniapp auth refused a non-admin user")
        raise HTTPException(status_code=403, detail="Admin only")
    return user_id
