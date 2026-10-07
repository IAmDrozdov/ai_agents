"""Notes endpoints for the Mini App: a thin adapter over apps/notes (ADR-016)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from notes.db import Database
from notes.domain import dashboard as dashboard_read
from notes.domain import items, sections, settings
from notes.domain.items import UNSET, DayField, Item, ItemFilter, Status, Unset

from .auth import require_admin

router = APIRouter(prefix="/api/notes", dependencies=[Depends(require_admin)])


class ItemPatch(BaseModel):
    """One Owner edit; every field is optional."""

    model_config = ConfigDict(extra="forbid")
    sections: list[str] | None = Field(default=None, max_length=50)
    status: Status | None = None
    text: str | None = Field(default=None, max_length=4096)  # Telegram's own message limit
    due: datetime | None = None  # a future moment sets or moves the Due, null removes it


class SectionIn(BaseModel):
    """A new Section; the domain validates the values, these limits only bound the request."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=200)
    emoji: str = Field(default="", max_length=50)
    color: str = Field(default="#8a8a8a", max_length=20)
    hint: str = Field(default="", max_length=1000)


class SectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=200)
    emoji: str | None = Field(default=None, max_length=50)
    color: str | None = Field(default=None, max_length=20)
    hint: str | None = Field(default=None, max_length=1000)


class OrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[int] = Field(max_length=200)


def get_db(request: Request) -> Database:
    return request.app.state.notes_db


DbDep = Annotated[Database, Depends(get_db)]


def _item_json(item: Item) -> dict[str, Any]:
    """An Item as the page reads it: the Due as ISO UTC, the rest as stored."""
    data = asdict(item) | {"overdue": item.is_overdue()}
    if item.due_at:
        data["due_at"] = _iso(item.due_at)
    return data


def _iso(stamped: str) -> str:
    return (
        datetime.strptime(stamped, items.TIMESTAMP)
        .replace(tzinfo=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _found(item: Item | None) -> Item:
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.get("/sections")
def get_sections(db: DbDep) -> dict[str, Any]:
    todo = sections.status_counts(db, "todo")
    done = sections.status_counts(db, "done")
    return {
        "sections": [
            asdict(section)
            | {"todo_count": todo.get(section.id, 0), "done_count": done.get(section.id, 0)}
            for section in sections.list_sections(db)
        ]
    }


@router.post("/sections", status_code=201)
def post_section(body: SectionIn, db: DbDep) -> dict[str, Any]:
    return asdict(sections.create_section(db, **body.model_dump()))


@router.put("/sections/order")
def put_section_order(body: OrderBody, db: DbDep) -> dict[str, Any]:
    return {"sections": [asdict(s) for s in sections.reorder_sections(db, body.ids)]}


@router.patch("/sections/{section_id}")
def patch_section(section_id: int, body: SectionPatch, db: DbDep) -> dict[str, Any]:
    section = sections.update_section(db, section_id, **body.model_dump(exclude_unset=True))
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")
    return asdict(section)


@router.delete("/sections/{section_id}", status_code=204)
def remove_section(section_id: int, db: DbDep) -> None:
    if not sections.delete_section(db, section_id):
        raise HTTPException(status_code=404, detail="Section not found")


@router.get("/dashboard")
def get_dashboard(db: DbDep, tz: Annotated[str, Query(max_length=64)] = "UTC") -> dict[str, Any]:
    settings.remember_zone(
        db, tz
    )  # every launch opens the Dashboard: the Owner's zone is learnt here
    board = dashboard_read.dashboard(db, tz)
    return {
        "todo": board.todo,
        "overdue": board.overdue,
        "captured": board.captured,
        "done": board.done,
        "from": board.first.isoformat(),
        "to": board.last.isoformat(),
    }


@router.get("/items")
def get_items(
    db: DbDep,
    section: Annotated[list[str] | None, Query(max_length=50)] = None,
    status: Status = "todo",
    q: Annotated[str, Query(max_length=200)] = "",
    overdue: bool = False,
    day: date | None = None,
    day_field: DayField = "captured",
    tz: Annotated[str, Query(max_length=64)] = "UTC",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    if day is not None and not date(2000, 1, 1) <= day <= date(2100, 1, 1):
        raise HTTPException(status_code=422, detail="day out of range")
    if overdue:  # the Overdue row: every Section, todo only, earliest Due first
        flt = ItemFilter(status="todo", overdue=True)
    else:
        flt = ItemFilter(
            sections=tuple(section or ()),
            status=None if q.strip() else status,  # Search covers both Statuses
            day=day,
            day_field=day_field,
            tz=tz,
            text=q,
        )
    page = items.query(db, flt, offset=offset, limit=limit)
    return {"items": [_item_json(item) for item in page.items], "total": page.total}


@router.get("/items/{item_id}")
def get_item(item_id: int, db: DbDep) -> dict[str, Any]:
    return _item_json(_found(items.get_item(db, item_id)))


@router.get("/items/{item_id}/preview")
def get_item_preview(item_id: int, db: DbDep) -> Response:
    preview = items.get_preview(db, item_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="No preview")
    data, mime = preview
    return Response(
        content=data, media_type=mime, headers={"Cache-Control": "private, max-age=3600"}
    )


@router.post("/items/{item_id}/reenrich")
def reenrich(item_id: int, db: DbDep) -> dict[str, Any]:
    item = _found(items.get_item(db, item_id))
    if item.enrichment_status == "pending":  # already queued or in flight: don't start it twice
        return _item_json(item)
    try:
        return _item_json(items.request_reenrich(db, item_id))
    except KeyError as exc:  # deleted between the read and the write
        raise HTTPException(status_code=404, detail="Item not found") from exc


@router.post("/items/{item_id}/show")
def show_in_chat(item_id: int, db: DbDep) -> dict[str, Any]:
    """Queue "Показать в чате": the bot's show loop replies to the original message (ADR-0008)."""
    item = _found(items.get_item(db, item_id))
    if item.tg_chat_id is None or item.tg_message_id is None:
        raise HTTPException(status_code=409, detail="No original message to show")
    return _item_json(_found(items.request_show(db, item_id)))


@router.patch("/items/{item_id}")
def patch_item(item_id: int, patch: ItemPatch, db: DbDep) -> dict[str, Any]:
    due: datetime | None | Unset = UNSET
    if "due" in patch.model_fields_set:
        if patch.due is not None and patch.due.tzinfo is None:
            raise HTTPException(status_code=422, detail="The Due needs a time zone")
        due = patch.due
    try:
        item = items.edit_item(
            db, item_id, sections=patch.sections, status=patch.status, text=patch.text, due=due
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Это время уже прошло") from exc
    return _item_json(_found(item))


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: DbDep) -> None:
    if not items.delete_item(db, item_id):
        raise HTTPException(status_code=404, detail="Item not found")
