"""biread-sync — the bookmark, never the book."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from . import auth, db, logs
from .shelf import Entry, forget, merge, read


@asynccontextmanager
async def lifespan(app: FastAPI):
    logs.install()
    db.start()
    auth.sweep()
    yield
    db.stop()


app = FastAPI(title="biread-sync", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/api/health")
def health() -> dict:
    db.one("select 1 as ok")
    return {"ok": True, "signIn": "github" if auth.configured() else None}


@app.get("/api/me")
def me(request: Request) -> dict:
    account = auth.account_of(request)
    if account is None:
        return {"signedIn": False}
    return {"signedIn": True, "handle": account["handle"],
            "provider": account["provider"]}


@app.get("/api/auth/github")
def sign_in(next: str | None = None) -> Response:
    url, state = auth.begin(next)
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(auth.STATE_COOKIE, state, max_age=600, httponly=True,
                        samesite="lax", secure=auth.secure_cookies())
    return response


@app.get("/api/auth/github/callback")
def callback(request: Request, code: str = "", state: str = "") -> Response:
    remembered = request.cookies.get(auth.STATE_COOKIE)
    token = auth.finish(code, state, remembered)
    response = RedirectResponse(auth.landing(remembered), status_code=302)
    response.delete_cookie(auth.STATE_COOKIE)
    response.set_cookie(auth.COOKIE, token, max_age=auth.SESSION_DAYS * 86400,
                        httponly=True, samesite="lax", secure=auth.secure_cookies())
    return response


@app.post("/api/auth/signout")
def sign_out(request: Request) -> Response:
    auth.sign_out(request)
    response = JSONResponse({"signedIn": False})
    response.delete_cookie(auth.COOKIE)
    return response


@app.get("/api/shelf")
def shelf(account: dict = Depends(auth.required)) -> dict:
    return {"books": read(account["id"])}


@app.put("/api/shelf/{book_id}")
def put(book_id: str, entry: Entry,
        account: dict = Depends(auth.required)) -> dict:
    if not book_id or len(book_id) > 128:
        raise HTTPException(400, "that is not a book id")
    try:
        merged = merge(account["id"], book_id, entry)
    except ValueError as full:
        raise HTTPException(409, str(full)) from full
    return {"books": merged}


@app.delete("/api/shelf/{book_id}")
def drop(book_id: str, account: dict = Depends(auth.required)) -> dict:
    forget(account["id"], book_id)
    return {"removed": book_id}
