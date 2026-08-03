"""One pool, one schema, opened when the app starts."""
from __future__ import annotations

import os
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DSN = os.environ.get("BIREAD_DATABASE_URL", "dbname=love")
SCHEMA = Path(__file__).resolve().parent.parent / "schema.sql"

pool = ConnectionPool(DSN, min_size=1, max_size=8, open=False,
                      kwargs={"row_factory": dict_row})


_holders = 0


def start() -> None:
    """Open the pool, or join one already open.

    Counted rather than flag-checked because a closed psycopg pool cannot be
    reopened: two overlapping holders — the app's lifespan inside a test that
    opened the pool itself — would otherwise leave the second one holding a
    corpse.
    """
    global _holders
    if _holders == 0:
        pool.open()
        pool.wait(timeout=10)
        with pool.connection() as conn:
            conn.execute(SCHEMA.read_text(encoding="utf-8"))
    _holders += 1


def stop() -> None:
    global _holders
    _holders = max(0, _holders - 1)
    if _holders == 0:
        pool.close()


def one(sql: str, params: tuple = ()) -> dict | None:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchone()


def rows(sql: str, params: tuple = ()) -> list[dict]:
    with pool.connection() as conn:
        return conn.execute(sql, params).fetchall()


def run(sql: str, params: tuple = ()) -> None:
    with pool.connection() as conn:
        conn.execute(sql, params)
