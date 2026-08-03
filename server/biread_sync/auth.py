"""Sign-in, and the session cookie that follows it.

GitHub only, for one practical reason: Google will not accept a bare IP address
as a redirect target, and there is no domain yet. The provider lives in one table
below so the second one is a row and a callback, not a rewrite.
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlparse

import requests
from fastapi import HTTPException, Request

from . import db

BASE_URL = os.environ.get("BIREAD_BASE_URL", "http://localhost:8080").rstrip("/")
SESSION_DAYS = int(os.environ.get("BIREAD_SESSION_DAYS", "90"))
COOKIE = "biread_session"
STATE_COOKIE = "biread_oauth_state"

GITHUB = {
    "authorize": "https://github.com/login/oauth/authorize",
    "token": "https://github.com/login/oauth/access_token",
    "user": "https://api.github.com/user",
    "client_id": os.environ.get("BIREAD_GITHUB_CLIENT_ID", ""),
    "client_secret": os.environ.get("BIREAD_GITHUB_CLIENT_SECRET", ""),
}


def configured() -> bool:
    return bool(GITHUB["client_id"] and GITHUB["client_secret"])


def secure_cookies() -> bool:
    """Only mark the cookie Secure once the site is actually https.

    Set it on a plain-http origin and the browser drops it, so sign-in would fail
    silently rather than insecurely — worse, and harder to see.
    """
    return BASE_URL.startswith("https://")


def local_path(target: str | None) -> str:
    """Where to land after signing in — this origin only.

    An unchecked `next` is an open redirect: a link to our own sign-in that ends
    on someone else's page, wearing our address as far as the reader can tell.
    """
    if not target:
        return "/"
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return "/"
    path = target if target.startswith("/") else "/" + target
    # `//evil.example` and `/\evil.example` are both read as another host by
    # browsers, and urlparse does not agree with them about it.
    return "/" if path[:2] in ("//", "/\\") else path


def begin(next_path: str | None) -> tuple[str, str]:
    """The URL to send the reader to, and the state to remember while they are gone."""
    if not configured():
        raise HTTPException(503, "sign-in is not configured on this server")
    state = secrets.token_urlsafe(24)
    query = urlencode({
        "client_id": GITHUB["client_id"],
        "redirect_uri": f"{BASE_URL}/api/auth/github/callback",
        "state": state,
        # No scopes. A public profile is all an identity needs, and asking for
        # more would be asking a reader to grant what we would never read.
        "scope": "",
        "allow_signup": "true",
    })
    return f"{GITHUB['authorize']}?{query}", f"{state}|{local_path(next_path)}"


def finish(code: str, state: str, remembered: str | None) -> str:
    """Trade the code for an identity, and open a session. Returns the cookie token."""
    if not remembered or "|" not in remembered:
        raise HTTPException(400, "this sign-in did not start here — try again")
    expected, _ = remembered.split("|", 1)
    if not secrets.compare_digest(state or "", expected):
        raise HTTPException(400, "this sign-in did not start here — try again")

    token = requests.post(
        GITHUB["token"],
        headers={"Accept": "application/json"},
        data={
            "client_id": GITHUB["client_id"],
            "client_secret": GITHUB["client_secret"],
            "code": code,
            "redirect_uri": f"{BASE_URL}/api/auth/github/callback",
        },
        timeout=15,
    ).json().get("access_token")
    if not token:
        raise HTTPException(502, "GitHub would not complete the sign-in")

    who = requests.get(
        GITHUB["user"],
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        timeout=15,
    ).json()
    if not who.get("id"):
        raise HTTPException(502, "GitHub returned no account")

    # The GitHub token is used here and dropped. Nothing of it is stored: we
    # wanted an identity, not access to anybody's repositories.
    account = db.one(
        """insert into account (provider, subject, handle)
           values ('github', %s, %s)
           on conflict (provider, subject)
           do update set handle = excluded.handle, seen_at = now()
           returning id""",
        (str(who["id"]), who.get("login")),
    )
    session = secrets.token_urlsafe(32)
    db.run(
        "insert into session (token, account_id, expires_at) values (%s, %s, %s)",
        (session, account["id"],
         datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)),
    )
    return session


def landing(remembered: str | None) -> str:
    if remembered and "|" in remembered:
        return remembered.split("|", 1)[1]
    return "/"


def account_of(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    return db.one(
        """select a.id, a.handle, a.provider
           from session s join account a on a.id = s.account_id
           where s.token = %s and s.expires_at > now()""",
        (token,),
    )


def required(request: Request) -> dict:
    account = account_of(request)
    if account is None:
        raise HTTPException(401, "sign in to sync your shelf")
    return account


def sign_out(request: Request) -> None:
    token = request.cookies.get(COOKIE)
    if token:
        db.run("delete from session where token = %s", (token,))


def sweep() -> None:
    db.run("delete from session where expires_at < now()")
