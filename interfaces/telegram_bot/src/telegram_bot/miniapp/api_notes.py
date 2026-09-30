"""Notes endpoints for the Mini App: a thin adapter over apps/notes (ADR-016)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from notes.db import Database
from notes.domain import items, sections
from notes.domain.items import Item, ItemFilter, Placement, Status

from .auth import require_admin

router = APIRouter(prefix="/api/notes", dependencies=[Depends(require_admin)])


class ItemPatch(BaseModel):
    """One Owner edit; every field is optional and an empty patch only marks the Item Reviewed."""

    model_config = ConfigDict(extra="forbid")
    sections: list[str] | None = Field(default=None, max_length=50)
    status: Status | None = None
    placement: Placement | None = None
    text: str | None = Field(default=None, max_length=4096)  # Telegram's own message limit
    reviewed: bool | None = None


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


class FilterBody(BaseModel):
    """The list filter, for actions that cover every page of it."""

    model_config = ConfigDict(extra="forbid")
    sections: list[str] = Field(default_factory=list, max_length=50)
    status: Status | None = None
    placement: Placement = "active"
    unreviewed: bool = False


def get_db(request: Request) -> Database:
    return request.app.state.notes_db


DbDep = Annotated[Database, Depends(get_db)]


def _found(item: Item | None) -> Item:
    if item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


@router.get("/sections")
def get_sections(db: DbDep) -> dict[str, Any]:
    counts = sections.active_counts(db)
    return {
        "sections": [
            asdict(section) | {"active_count": counts.get(section.id, 0)}
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


@router.get("/items")
def get_items(
    db: DbDep,
    section: Annotated[list[str] | None, Query(max_length=50)] = None,
    status: Status | None = None,
    placement: Placement = "active",
    unreviewed: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    flt = ItemFilter(
        sections=tuple(section or ()), status=status, placement=placement, unreviewed=unreviewed
    )
    page = items.query(db, flt, offset=offset, limit=limit)
    return {"items": [asdict(item) for item in page.items], "total": page.total}


@router.get("/items/{item_id}")
def get_item(item_id: int, db: DbDep) -> dict[str, Any]:
    return asdict(_found(items.get_item(db, item_id)))


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
        return asdict(item)
    try:
        return asdict(items.request_reenrich(db, item_id))
    except KeyError as exc:  # deleted between the read and the write
        raise HTTPException(status_code=404, detail="Item not found") from exc


@router.patch("/items/{item_id}")
def patch_item(item_id: int, patch: ItemPatch, db: DbDep) -> dict[str, Any]:
    item = items.edit_item(
        db,
        item_id,
        sections=patch.sections,
        status=patch.status,
        placement=patch.placement,
        text=patch.text,
        reviewed=True if patch.reviewed is None else patch.reviewed,
    )
    return asdict(_found(item))


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, db: DbDep) -> None:
    try:
        deleted = items.delete_trashed(db, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Only a trashed item can be deleted") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")


@router.post("/bulk/archive-done")
def bulk_archive_done(db: DbDep) -> dict[str, int]:
    return {"count": items.archive_done(db)}


@router.post("/bulk/mark-reviewed")
def bulk_mark_reviewed(body: FilterBody, db: DbDep) -> dict[str, int]:
    flt = ItemFilter(
        sections=tuple(body.sections),
        status=body.status,
        placement=body.placement,
        unreviewed=body.unreviewed,
    )
    return {"count": items.mark_reviewed(db, flt)}


@router.post("/bulk/empty-trash")
def bulk_empty_trash(db: DbDep) -> dict[str, int]:
    return {"count": items.empty_trash(db)}
