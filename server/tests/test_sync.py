"""The merge rule, the guards around it, and the way in.

Needs a real Postgres — the interesting behaviour is in `on conflict … where`,
which a fake would only reimplement wrongly. Point BIREAD_DATABASE_URL at a
throwaway database; the tests empty it between themselves.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("BIREAD_DATABASE_URL", "dbname=biread_test")
os.environ.setdefault("BIREAD_BASE_URL", "http://localhost:8080")

from fastapi.testclient import TestClient  # noqa: E402

from biread_sync import auth, db  # noqa: E402
from biread_sync.app import app  # noqa: E402

NOW = datetime.now(timezone.utc)
EARLIER = NOW - timedelta(hours=1)
LATER = NOW + timedelta(hours=1)


def stamp(when: datetime) -> str:
    return when.isoformat()


@pytest.fixture(scope="session")
def live():
    try:
        db.start()
    except Exception as unreachable:            # pragma: no cover - no database here
        pytest.skip(f"no Postgres: {unreachable}")
    yield
    db.stop()


@pytest.fixture
def client(live):
    db.run("truncate account restart identity cascade")
    with TestClient(app) as client:
        yield client


@pytest.fixture
def reader(client):
    """A signed-in reader, made the way sign-in makes one, minus the trip to GitHub."""
    account = db.one(
        """insert into account (provider, subject, handle)
           values ('github', %s, 'reader') returning id""", (secrets.token_hex(4),))
    token = secrets.token_urlsafe(16)
    db.run("insert into session (token, account_id, expires_at) values (%s, %s, %s)",
           (token, account["id"], NOW + timedelta(days=1)))
    client.cookies.set(auth.COOKIE, token)
    return client


def book(**over) -> dict:
    return {"title": "Candide", "author": "Voltaire", "lang": "english",
            "position": {"h": "p1", "frac": 0.25},
            "updatedAt": stamp(NOW), **over}


def test_health_needs_no_session(client):
    assert client.get("/api/health").json()["ok"] is True


def test_a_stranger_has_no_shelf(client):
    assert client.get("/api/me").json() == {"signedIn": False}
    assert client.get("/api/shelf").status_code == 401
    assert client.put("/api/shelf/abc", json=book()).status_code == 401


def test_a_book_comes_back_as_it_went_in(reader):
    reader.put("/api/shelf/hash-1", json=book())
    got = reader.get("/api/shelf").json()["books"]
    assert len(got) == 1
    assert got[0]["title"] == "Candide"
    assert got[0]["position"] == {"h": "p1", "frac": 0.25}


def test_turning_a_page_sends_only_a_position(reader):
    reader.put("/api/shelf/hash-1", json=book())
    reader.put("/api/shelf/hash-1", json={"position": {"h": "p9", "frac": 0.5},
                                          "updatedAt": stamp(LATER)})
    entry = reader.get("/api/shelf").json()["books"][0]
    assert entry["position"]["h"] == "p9"
    assert entry["title"] == "Candide", "a partial update must not blank the rest"


def test_a_stale_device_does_not_drag_the_page_back(reader):
    reader.put("/api/shelf/hash-1", json=book(position={"h": "p9", "frac": 0.5},
                                              updatedAt=stamp(LATER)))
    reader.put("/api/shelf/hash-1", json=book(position={"h": "p2", "frac": 0.1},
                                              updatedAt=stamp(EARLIER)))
    entry = reader.get("/api/shelf").json()["books"][0]
    assert entry["position"]["h"] == "p9"


def test_corrections_from_two_devices_are_both_kept(reader):
    reader.put("/api/shelf/hash-1", json=book(edits=[
        {"h": "para-a", "baseHash": "b-a", "text": "caught wind of it",
         "updatedAt": stamp(NOW)}]))
    reader.put("/api/shelf/hash-1", json=book(edits=[
        {"h": "para-b", "baseHash": "b-b", "text": "a most sweet disposition",
         "updatedAt": stamp(NOW)}]))
    edits = {e["h"]: e["text"] for e in reader.get("/api/shelf").json()["books"][0]["edits"]}
    assert edits == {"para-a": "caught wind of it",
                     "para-b": "a most sweet disposition"}


def test_the_same_paragraph_keeps_the_newer_fix(reader):
    reader.put("/api/shelf/hash-1", json=book(edits=[
        {"h": "para-a", "baseHash": "b", "text": "second thoughts",
         "updatedAt": stamp(LATER)}]))
    reader.put("/api/shelf/hash-1", json=book(edits=[
        {"h": "para-a", "baseHash": "b", "text": "first thoughts",
         "updatedAt": stamp(EARLIER)}]))
    edits = reader.get("/api/shelf").json()["books"][0]["edits"]
    assert [e["text"] for e in edits] == ["second thoughts"]


def test_a_book_taken_off_the_shelf_takes_its_corrections_with_it(reader):
    reader.put("/api/shelf/hash-1", json=book(edits=[
        {"h": "para-a", "baseHash": "b", "text": "x", "updatedAt": stamp(NOW)}]))
    reader.delete("/api/shelf/hash-1")
    assert reader.get("/api/shelf").json()["books"] == []
    assert db.rows("select 1 from edit") == []


def test_two_readers_never_see_each_other(reader, client):
    reader.put("/api/shelf/hash-1", json=book())
    other = db.one("""insert into account (provider, subject, handle)
                      values ('github', 'other', 'other') returning id""")
    token = secrets.token_urlsafe(16)
    db.run("insert into session (token, account_id, expires_at) values (%s, %s, %s)",
           (token, other["id"], NOW + timedelta(days=1)))
    reader.cookies.set(auth.COOKIE, token)
    assert reader.get("/api/shelf").json()["books"] == []


def test_a_correction_may_not_be_a_chapter(reader):
    huge = {"h": "para-a", "baseHash": "b", "text": "x" * 5000,
            "updatedAt": stamp(NOW)}
    assert reader.put("/api/shelf/hash-1", json=book(edits=[huge])).status_code == 422


def test_the_paragraph_being_replaced_is_never_stored(reader):
    reader.put("/api/shelf/hash-1", json=book(edits=[
        {"h": "para-a", "baseHash": "b", "text": "the reader's own sentence",
         "updatedAt": stamp(NOW)}]))
    columns = db.rows("""select column_name from information_schema.columns
                         where table_name = 'edit'""")
    assert {c["column_name"] for c in columns} == {
        "account_id", "book_id", "para_hash", "base_hash", "text", "updated_at"}


def test_signing_out_ends_the_session(reader):
    assert reader.post("/api/auth/signout").json() == {"signedIn": False}
    assert reader.get("/api/shelf").status_code == 401


def test_an_expired_session_is_not_a_session(reader):
    db.run("update session set expires_at = now() - interval '1 day'")
    assert reader.get("/api/shelf").status_code == 401


@pytest.mark.parametrize("target,landing", [
    ("https://elsewhere.example/x", "/"),
    ("//elsewhere.example/x", "/"),
    ("books/candide.html", "/books/candide.html"),
    ("/books/candide.html", "/books/candide.html"),
    (None, "/"),
])
def test_sign_in_only_ever_lands_on_this_site(target, landing):
    assert auth.local_path(target) == landing


def test_sign_in_says_so_when_it_is_not_configured(client, monkeypatch):
    monkeypatch.setitem(auth.GITHUB, "client_id", "")
    assert client.get("/api/auth/github", follow_redirects=False).status_code == 503


def test_a_sign_in_that_started_elsewhere_is_refused(client):
    assert client.get("/api/auth/github/callback?code=x&state=y",
                      follow_redirects=False).status_code == 400


# ---------- what the log is allowed to remember ----------

@pytest.mark.parametrize("path,logged", [
    ("/api/auth/github/callback?code=abc123&state=xyz789",
     "/api/auth/github/callback?code=<redacted>&state=<redacted>"),
    # The one thing you actually want to see when a sign-in goes wrong.
    ("/api/auth/github?next=/books/candide.html",
     "/api/auth/github?next=/books/candide.html"),
    ("/api/shelf", "/api/shelf"),
    ("/api/shelf?", "/api/shelf?"),
    ("/api/x?token=t&api_key=k&page=2",
     "/api/x?token=<redacted>&api_key=<redacted>&page=2"),
])
def test_a_credential_never_reaches_the_log(path, logged):
    from biread_sync.logs import scrub
    assert scrub(path) == logged


def test_the_filter_leaves_records_it_does_not_understand_alone():
    import logging
    from biread_sync.logs import Scrubbed
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0,
                               "something else", ("only", "two"), None)
    assert Scrubbed().filter(record) is True
    assert record.args == ("only", "two")
