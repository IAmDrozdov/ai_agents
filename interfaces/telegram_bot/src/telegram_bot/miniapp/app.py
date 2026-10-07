"""FastAPI app for the admin Mini App: a public static shell plus a signed JSON API (ADR-016, ADR-019)."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from notes.db import Database
from notes.domain.sections import SectionError

from .. import db
from . import api_notes, api_usage, auth

STATIC = Path(__file__).parent / "static"
IMMUTABLE = "public, max-age=31536000, immutable"

CSP = (
    "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; "
    "img-src 'self' https: data: blob:; connect-src 'self'; frame-ancestors https://web.telegram.org; "
    "base-uri 'none'; form-action 'none'"
)


def build_id(directory: Path) -> str:
    """A short hash over every static file, so it changes whenever any of them does."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


def render_shell(directory: Path, build: str) -> str:
    """index.html with versioned asset URLs and a modulepreload for every module: one fetch level."""
    html = (directory / "index.html").read_text(encoding="utf-8")
    modules = sorted(p.name for p in directory.glob("*.js"))
    links = "\n  ".join(f'<link rel="modulepreload" href="/static/{name}">' for name in modules)
    return html.replace("<!-- modulepreload -->", links).replace('"/static/', f'"/static/{build}/')


def create_app(notes_db: Database) -> FastAPI:
    db.init_db()
    build = build_id(STATIC)
    shell = render_shell(STATIC, build)
    shell_etag = f'"{hashlib.sha256(shell.encode()).hexdigest()[:12]}"'
    app = FastAPI(title="miniapp", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.init_secret = auth.init_secret()
    app.state.notes_db = notes_db
    # Any build segment serves the current files, so a shell from before a deploy still loads.
    app.mount("/static/{build}", StaticFiles(directory=STATIC), name="assets")
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.include_router(api_usage.router)
    app.include_router(api_notes.router)
    # Inside the header middleware: that one streams every response, which gzip would compress regardless of size.
    app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)

    @app.middleware("http")
    async def secure_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        path = request.url.path
        if path.startswith(f"/static/{build}/") and response.status_code in (200, 304):
            response.headers["Cache-Control"] = IMMUTABLE
        else:
            # The shell is revalidated so a deploy reaches the webview; a route may set its own.
            default = "no-store" if path.startswith("/api/") else "no-cache"
            response.headers.setdefault("Cache-Control", default)
        return response

    @app.exception_handler(SectionError)
    async def section_error(request: Request, exc: SectionError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def index(request: Request) -> Response:
        sent = request.headers.get("if-none-match", "")
        if shell_etag in (tag.strip().removeprefix("W/") for tag in sent.split(",")):
            return Response(status_code=304, headers={"ETag": shell_etag})
        return HTMLResponse(shell, headers={"ETag": shell_etag})

    return app
