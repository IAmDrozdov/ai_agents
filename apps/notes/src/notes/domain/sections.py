"""Sections: the categories Items are filed under. Other always exists (ADR-0002)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from notes.db import Database

OTHER_SLUG = "other"

# slug, name, emoji, color, hint — position is the list order.
STARTER_SECTIONS: tuple[tuple[str, str, str, str, str], ...] = (
    ("watch", "Посмотреть", "🍿", "#e0523f", "Видео, фильмы, сериалы, ролики, стримы, лекции"),
    ("read", "Почитать", "📖", "#3f7fe0", "Статьи, книги, треды, посты, документация"),
    ("eat", "Поесть", "🍜", "#e09a3f", "Рестораны, кафе, бары, рецепты, еда и напитки"),
    ("buy", "Купить", "🛒", "#8f3fe0", "Товары, гаджеты, одежда, подарки, всё что покупают"),
    ("go", "Сходить", "📍", "#3fb8a0", "Места, мероприятия, выставки, концерты, поездки"),
    ("work", "Работа", "💼", "#5c6b7a", "Полезное для работы: инструменты, практики, карьера"),
    ("pet", "Пет-проекты", "🛠", "#3fa04a", "Библиотеки, идеи, туториалы и код для своих проектов"),
    (OTHER_SLUG, "Остальное", "📦", "#8a8a8a", "Всё, что не подходит ни под одну секцию"),
)


@dataclass(frozen=True)
class Section:
    id: int
    slug: str
    name: str
    emoji: str
    color: str
    hint: str
    is_builtin: bool
    position: int


def _row_to_section(row: sqlite3.Row) -> Section:
    return Section(
        id=int(row["id"]),
        slug=row["slug"],
        name=row["name"],
        emoji=row["emoji"],
        color=row["color"],
        hint=row["hint"],
        is_builtin=bool(row["is_builtin"]),
        position=int(row["position"]),
    )


def seed_sections(db: Database) -> None:
    """Insert the starter set once; existing slugs are left untouched."""
    with db.session() as conn:
        for position, (slug, name, emoji, color, hint) in enumerate(STARTER_SECTIONS):
            conn.execute(
                "INSERT OR IGNORE INTO sections(slug, name, emoji, color, hint, is_builtin, position) "
                "VALUES (?, ?, ?, ?, ?, 1, ?)",
                (slug, name, emoji, color, hint, position),
            )


def list_sections(db: Database) -> list[Section]:
    with db.session(readonly=True) as conn:
        rows = conn.execute("SELECT * FROM sections ORDER BY position, id").fetchall()
    return [_row_to_section(row) for row in rows]


def get_section(db: Database, section_id: int) -> Section | None:
    with db.session(readonly=True) as conn:
        row = conn.execute("SELECT * FROM sections WHERE id=?", (section_id,)).fetchone()
    return _row_to_section(row) if row else None


def get_section_by_slug(db: Database, slug: str) -> Section | None:
    with db.session(readonly=True) as conn:
        row = conn.execute("SELECT * FROM sections WHERE slug=?", (slug,)).fetchone()
    return _row_to_section(row) if row else None


def other_id(db: Database) -> int:
    other = get_section_by_slug(db, OTHER_SLUG)
    if other is None:
        raise RuntimeError("the Other section is missing — was the database initialised?")
    return other.id
