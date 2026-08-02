"""Assemble the deployable in-browser builder into web/dist/.

Builds the biread wheel and gathers the static files a host needs — the page,
the worker, the wheel, and the fonts. Pyodide itself loads from a CDN, so the
output is a handful of files you can drop on any static host.

    python web/build.py        # -> web/dist/, ready to serve or deploy
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DIST = WEB / "dist"
BOOKS = WEB / "books"
FONTS = ROOT / "biread" / "assets" / "fonts"
FONT_FILES = ("charis-sil-400.woff2", "charis-sil-400-italic.woff2")

# --- books already made ------------------------------------------------------
#
# A shelf card hands over a finished book only where one was built, read, and
# approved here. Every other card stays what it was — tap it and build the book
# yourself — because a book going out under biread's name is a thing somebody
# decided, not a thing that happened to align.
#
# What a card *claims* is measured off the file in `measure`, never declared, so
# replacing a build updates the card and cannot drift from it. Two things are
# stated here because no file can say them about itself: which English edition
# is inside, and that a person approved it.
#
# `BOOKS_AT` is where the finished books are served from. Empty means beside the
# builder, which is what a static host gives you and what localhost gives you
# now. The day there is a server, this line is the only one that changes.
BOOKS_AT = ""
PUBLISHED = [
    {
        "slug": "micromegas",
        "file": "micromegas.html",
        "english": "Phalen",
        "approved": "2026-08-01",
    },
    {
        "slug": "candide",
        "file": "candide.html",
        "english": "Smollett · 1920",
        "approved": "2026-08-01",
    },
]

# A book published without glosses can still be glossed — by whoever reads it, a
# page at a time, on their own key. Set here rather than per book because it is
# one question ("can a reader add these?") with one answer, and a book that
# already carries glosses ignores it.
GLOSS_ON_DEMAND = {"provider": "openrouter", "model": "deepseek/deepseek-chat-v3.1"}

BOOK_DATA = re.compile(
    r'<script type="application/json" id="book-data">(.*?)</script>', re.S)


def measure(path: Path) -> dict:
    """What a finished book says about itself.

    A card may claim only what its source says, and the source here is the book:
    how much of it carries a translation, whether the published edition rides
    beside ours or stands as the one column, how much of it is glossed, and what
    it holds for offline reading. None of it is typed by hand, so a card cannot
    outlive the file it describes.
    """
    found = BOOK_DATA.search(path.read_text(encoding="utf-8"))
    if not found:
        raise SystemExit(f"{path.name} carries no book data — is it a built reader?")
    data = json.loads(found.group(1))
    pairs = data["pairs"]
    return {
        "bytes": path.stat().st_size,
        "paragraphs": len(pairs),
        "translated": sum(1 for p in pairs if p.get("en", "").strip()),
        "glossed": sum(1 for p in pairs if p.get("units")),
        "published": bool(data.get("publishedAvailable")),
        "solo": bool(data.get("solo")),
        "formats": [d["format"] for d in data.get("downloads", [])],
    }


def gather_published(catalogue: dict) -> None:
    """Attach each finished book to its shelf card, and copy it into the bundle.

    Loud on every mismatch: a slug that names no shelf book, or a file that is
    not there, is a card promising a download that would 404 in front of a
    reader. Better to stop the build than to ship the promise.
    """
    from biread.render import download_name, rewrap

    by_slug = {book["slug"]: book for book in catalogue["books"]}
    if PUBLISHED:
        (DIST / "books").mkdir(exist_ok=True)
    for entry in PUBLISHED:
        book = by_slug.get(entry["slug"])
        if book is None:
            raise SystemExit(f"published book {entry['slug']!r} is not on the shelf")
        source = BOOKS / entry["file"]
        if not source.is_file():
            raise SystemExit(f"published book {entry['slug']!r} has no file at {source}")
        # The checked-in file stays the book as it was approved; what the bundle
        # serves is that book set in today's reader, and told where a reader may
        # buy the glosses it lacks. A published file otherwise carries whatever
        # reader it was built with, so a shelf would quietly hand out old ones.
        served = DIST / "books" / entry["file"]
        served.write_text(
            rewrap(source.read_text(encoding="utf-8"), gloss_on_demand=GLOSS_ON_DEMAND),
            encoding="utf-8")
        book["prebuilt"] = {
            "href": f"{BOOKS_AT}books/{entry['file']}",
            "filename": download_name(book["title"]) + ".html",
            "english": entry.get("english"),
            "approved": entry["approved"],
            # Measured on what is served, not on what is checked in: the size a
            # card quotes is the size a reader downloads.
            **measure(served),
        }


def main() -> None:
    DIST.mkdir(parents=True, exist_ok=True)
    for stale in DIST.glob("*.whl"):
        stale.unlink()

    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps", "-w", str(DIST)],
        check=True,
    )
    wheel = next(DIST.glob("biread-*.whl"), None)
    if wheel is None:
        raise SystemExit("no biread wheel was produced")

    # The worker installs the wheel by exact name; fail loudly if they drift.
    if wheel.name not in (WEB / "worker.js").read_text(encoding="utf-8"):
        raise SystemExit(
            f"worker.js does not reference {wheel.name}. Update its wheel filename "
            f"to match the version in pyproject.toml."
        )

    for name in ("builder.html", "worker.js"):
        shutil.copy2(WEB / name, DIST / name)
    for font in FONT_FILES:
        shutil.copy2(FONTS / font, DIST / font)

    # The shelf is a fixed list of books that changes only when this runs, and it
    # was arriving behind a Python runtime booting from a CDN — four seconds on a
    # warm cache and worse on a first visit, to paint eight cards. Written out
    # here instead, so the page has it before the engine exists.
    from biread.shelf import catalogue

    shelf = catalogue()
    gather_published(shelf)
    (DIST / "shelf.json").write_text(
        json.dumps(shelf, ensure_ascii=False), encoding="utf-8")

    files = sorted(p.name for p in DIST.iterdir() if p.is_file())
    print(f"Built {DIST.relative_to(ROOT)}/ — {len(files)} files: {', '.join(files)}")
    for entry in PUBLISHED:
        book = next(b for b in shelf["books"] if b["slug"] == entry["slug"])
        made = book["prebuilt"]
        print(f"  ready to read: {book['title']} — {made['paragraphs']} paragraphs, "
              f"{made['glossed']} glossed, {made['bytes'] / 1e6:.1f} MB")
    print("Try it locally:  python -m http.server -d web/dist   (then open /builder.html)")


if __name__ == "__main__":
    main()
