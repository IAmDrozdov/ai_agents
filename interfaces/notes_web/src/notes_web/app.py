"""FastAPI app: the Items list and re-enrich."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from notes.db import Database
from notes.domain import items, sections

HERE = Path(__file__).parent


def create_app(db: Database) -> FastAPI:
    app = FastAPI(title="notes", docs_url=None, redoc_url=None)
    # Loopback by deploy; the Host check stops a DNS-rebinding page from reading through the tunnel.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    app.state.db = db

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"items": items.query(db), "sections": sections.list_sections(db)},
        )

    @app.post("/items/{item_id}/reenrich")
    def reenrich(item_id: int) -> RedirectResponse:
        if items.get_item(db, item_id) is None:
            raise HTTPException(status_code=404)
        items.request_reenrich(db, item_id)
        return RedirectResponse(url="/", status_code=303)

    return app
