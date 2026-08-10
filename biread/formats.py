"""Give a finished book its EPUB or PDF, whoever made it and whenever.

A book built in the browser carries no file to take away: both exporters lay the
spread out by measuring real type in headless Chromium, and a reader's own tab
has no way to run one. That is honest at build time and useless afterwards — the
book is on their disk, the typesetting needs nothing but the book, and there was
no way to ask for it.

    python -m biread.formats "la nausee - bilingual reader.html"
    python -m biread.formats book.html --pdf          # both
    python -m biread.formats *.html --remake          # after the exporter changed

The file gains the format inside itself, which is where a download has always
lived here: the book stays one thing to keep and to pass on. Nothing is fetched
and nothing is charged — the book on disk is the whole source.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .errors import BireadError
from .render import BOOK_DATA_RE, add_downloads

#: A file made and put inside the book: (format, its size in bytes).
Typeset = tuple[str, int]


def add_formats(path: Path, formats: list[str], remake: bool = False,
                author: str = "") -> list[Typeset]:
    """Typeset one finished book in place, leaving every word of it alone.

    A format the book already carries is left as it is, so this can be run over a
    whole shelf for the cost of the books actually missing one — `remake` is for
    the case that cannot see, an exporter that has itself changed since.

    `author` is the one thing a finished book does not say about itself; without
    one the title page and the metadata simply do not claim it.
    """
    from .export.refit import formats_from_html

    html = path.read_text(encoding="utf-8", errors="replace")
    found = BOOK_DATA_RE.search(html)
    if not found:
        raise BireadError(
            f"{path.name} is not a book biread made — it carries no book data. "
            f"This takes the finished HTML a build hands you, not the source you "
            f"built it from.")
    carried = {entry["format"] for entry in json.loads(found.group(2)).get("downloads") or []}
    wanted = [fmt for fmt in formats if remake or fmt not in carried]
    if not wanted:
        return []

    with tempfile.TemporaryDirectory() as tmp:
        downloads = formats_from_html(html, Path(tmp), wanted, author=author)
    path.write_text(add_downloads(html, downloads), encoding="utf-8")
    return [(fmt, len(blob)) for fmt, _source, _filename, blob in downloads]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m biread.formats",
        description="Put an EPUB (and a PDF, if you ask) inside a book already built.")
    parser.add_argument("books", nargs="+", type=Path, metavar="BOOK.html",
                        help="the finished reader file a build handed you")
    parser.add_argument("--pdf", action="store_true",
                        help="a PDF as well as the EPUB: the print layout, two columns")
    parser.add_argument("--epub", dest="epub", action="store_true", default=None,
                        help="the EPUB only (the default)")
    parser.add_argument("--remake", action="store_true",
                        help="typeset again even where the book already carries the "
                             "format. For when the exporter itself has changed")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    formats = ["epub"] + (["pdf"] if args.pdf else [])

    for path in args.books:
        if not path.is_file():
            print(f"No file at {path}", file=sys.stderr)
            return 2
        try:
            made = add_formats(path, formats, remake=args.remake)
        except BireadError as exc:
            print(f"\n{exc}", file=sys.stderr)
            return 1
        if not made:
            print(f"{path.name}: already carries it, left alone")
            continue
        files = ", ".join(f"{fmt.upper()} {size / 1e6:.1f} MB" for fmt, size in made)
        print(f"{path.name}: {files} — the book is now "
              f"{path.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
