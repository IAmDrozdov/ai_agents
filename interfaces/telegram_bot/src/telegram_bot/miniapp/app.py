"""FastAPI app for the admin Mini App: a public static shell plus a signed JSON API (ADR-016)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from notes.db import Database
from notes.domain.sections import SectionError

from .. import db
from . import api_notes, api_usage, auth

HERE = Path(__file__).parent

CSP = (
    "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; "
    "img-src 'self' https: data: blob:; connect-src 'self'; frame-ancestors https://web.telegram.org; "
    "base-uri 'none'; form-action 'none'"
)


def create_app(notes_db: Database) -> FastAPI:
    db.init_db()
    app = FastAPI(title="miniapp", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.init_secret = auth.init_secret()
    app.state.notes_db = notes_db
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    app.include_router(api_usage.router)
    app.include_router(api_notes.router)

    @app.middleware("http")
    async def secure_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # The webview must revalidate the shell after a deploy; API answers are never cached.
        api = request.url.path.startswith("/api/")
        response.headers["Cache-Control"] = "no-store" if api else "no-cache"
        return response

    @app.exception_handler(SectionError)
    async def section_error(request: Request, exc: SectionError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(HERE / "static" / "index.html")

    return app
