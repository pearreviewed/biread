"""What a shelf entry is, and how two devices' versions of one become one.

The merge rule is the spec's, and it needs no conflict resolution of its own: a
position is last-write-wins by the client's own clock, and corrections merge per
paragraph, because every correction is already keyed to the paragraph it belongs
to. Two devices reading the same book converge.
"""
from __future__ import annotations

from datetime import datetime, timezone

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from . import db

# Ceilings, not guesses. They exist so that no sequence of well-formed requests
# adds up to a book sitting in this database: a correction is one sentence a
# reader wrote, and a hash is a hash.
HASH = 128
LABEL = 300
CORRECTION = 4000
EDITS_PER_REQUEST = 500
EDITS_PER_BOOK = 5000
BOOKS_PER_ACCOUNT = 2000


class Position(BaseModel):
    h: str = Field(max_length=HASH)
    frac: float = Field(ge=0, le=1, default=0)


class Edit(BaseModel):
    h: str = Field(max_length=HASH)
    baseHash: str = Field(max_length=HASH)
    text: str = Field(max_length=CORRECTION)
    updatedAt: datetime


class Entry(BaseModel):
    title: str | None = Field(default=None, max_length=LABEL)
    author: str | None = Field(default=None, max_length=LABEL)
    lang: str | None = Field(default=None, max_length=40)
    position: Position | None = None
    updatedAt: datetime | None = None
    edits: list[Edit] = Field(default_factory=list, max_length=EDITS_PER_REQUEST)


def _utc(when: datetime | None) -> datetime:
    when = when or datetime.now(timezone.utc)
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def read(account_id: int, book_id: str | None = None) -> list[dict]:
    where = "where account_id = %s" + (" and book_id = %s" if book_id else "")
    params = (account_id, book_id) if book_id else (account_id,)
    entries = db.rows(
        f"""select book_id, title, author, lang, position, updated_at
            from shelf_entry {where} order by updated_at desc""", params)
    edits = db.rows(
        f"""select book_id, para_hash, base_hash, text, updated_at
            from edit {where} order by updated_at""", params)
    by_book: dict[str, list] = {}
    for row in edits:
        by_book.setdefault(row["book_id"], []).append({
            "h": row["para_hash"],
            "baseHash": row["base_hash"],
            "text": row["text"],
            "updatedAt": row["updated_at"],
        })
    return [{
        "bookId": entry["book_id"],
        "title": entry["title"],
        "author": entry["author"],
        "lang": entry["lang"],
        "position": entry["position"],
        "updatedAt": entry["updated_at"],
        "edits": by_book.get(entry["book_id"], []),
    } for entry in entries]


def merge(account_id: int, book_id: str, incoming: Entry) -> list[dict]:
    stamp = _utc(incoming.updatedAt)
    with db.pool.connection() as conn, conn.transaction():
        held = conn.execute(
            "select count(*) as n from shelf_entry where account_id = %s",
            (account_id,)).fetchone()["n"]
        known = conn.execute(
            "select updated_at from shelf_entry where account_id = %s and book_id = %s",
            (account_id, book_id)).fetchone()
        if known is None and held >= BOOKS_PER_ACCOUNT:
            raise ValueError("this shelf is full")

        # A partial PUT is the common one — a reader who only turned a page sends
        # only a position — so absent fields keep what is already there.
        newer = known is None or stamp >= known["updated_at"]
        conn.execute(
            """insert into shelf_entry
                   (account_id, book_id, title, author, lang, position, updated_at)
               values (%s, %s, %s, %s, %s, %s, %s)
               on conflict (account_id, book_id) do update set
                   title      = case when %s then coalesce(excluded.title, shelf_entry.title)
                                     else shelf_entry.title end,
                   author     = case when %s then coalesce(excluded.author, shelf_entry.author)
                                     else shelf_entry.author end,
                   lang       = case when %s then coalesce(excluded.lang, shelf_entry.lang)
                                     else shelf_entry.lang end,
                   position   = case when %s then coalesce(excluded.position, shelf_entry.position)
                                     else shelf_entry.position end,
                   updated_at = greatest(shelf_entry.updated_at, excluded.updated_at)""",
            (account_id, book_id, incoming.title, incoming.author, incoming.lang,
             _json(incoming.position), stamp, newer, newer, newer, newer))

        if incoming.edits:
            room = conn.execute(
                "select count(*) as n from edit where account_id = %s and book_id = %s",
                (account_id, book_id)).fetchone()["n"]
            if room + len(incoming.edits) > EDITS_PER_BOOK:
                raise ValueError("this book holds as many corrections as it can")
            for edit in incoming.edits:
                conn.execute(
                    """insert into edit
                           (account_id, book_id, para_hash, base_hash, text, updated_at)
                       values (%s, %s, %s, %s, %s, %s)
                       on conflict (account_id, book_id, para_hash) do update set
                           base_hash  = excluded.base_hash,
                           text       = excluded.text,
                           updated_at = excluded.updated_at
                       where excluded.updated_at >= edit.updated_at""",
                    (account_id, book_id, edit.h, edit.baseHash, edit.text,
                     _utc(edit.updatedAt)))
    return read(account_id, book_id)


def forget(account_id: int, book_id: str) -> None:
    db.run("delete from shelf_entry where account_id = %s and book_id = %s",
           (account_id, book_id))


def _json(position: Position | None):
    return Jsonb(position.model_dump()) if position else None
