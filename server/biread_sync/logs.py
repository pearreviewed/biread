"""Keep credentials out of the access log.

GitHub hands back its one-time code in the query string, so uvicorn's access line
records it verbatim and it survives in the journal long after the code itself is
dead. The code is single-use and expires in minutes, so this is hygiene rather
than a hole — but a credential written to a log is a credential written to a log,
and the fix costs nothing.

Values are redacted by name, not the whole query: `next=/books/candide.html` is
exactly what you want to see when a sign-in goes wrong, and hiding it to hide the
code would trade one small problem for a worse one.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode

SECRET = {"code", "state", "token", "access_token", "secret", "key", "api_key"}


def scrub(path: str) -> str:
    head, sep, query = path.partition("?")
    if not sep or not query:
        return path
    kept = [(name, "<redacted>" if name.lower() in SECRET else value)
            for name, value in parse_qsl(query, keep_blank_values=True)]
    return head + "?" + urlencode(kept, safe="/<>")


class Scrubbed(logging.Filter):
    """uvicorn's access record carries (addr, method, path, version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (args[0], args[1], scrub(args[2]), args[3], args[4])
        return True


def install() -> None:
    logging.getLogger("uvicorn.access").addFilter(Scrubbed())
