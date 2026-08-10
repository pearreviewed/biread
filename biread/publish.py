"""Take a book from the shelf's two page names to a file ready to hand out.

Adding a book to the shelf used to be six things done by hand: build it, look at
it, copy the file, write a row, rebuild the bundle, remember which of those you
had done. The shelf is meant to grow, and the thing standing in the way was
never the money — it is about a dollar for a novel — but the number of steps
between deciding and having.

So: one command to make the book, one to approve it, and nothing in between that
has to be remembered.

    python -m biread.publish candide --dry-run     # what it would cost, no calls
    python -m biread.publish candide               # fetch, align, render, check
    python -m biread.publish candide --approve     # put it on the shelf
    python -m biread.publish all --formats         # give every shelf book its EPUB

Approval is deliberately its own step. A book that merely aligned is not a book
somebody vouched for, and the whole difference between this shelf and a search
box is that a person looked.

`--formats` is the one step here that acts on the book rather than making it. It
reads the finished file, typesets it, and puts the result back inside — so a book
gains its EPUB in the minutes the typesetting takes, and not the fetching, the
matching and the money of a build that has already been done.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .build import build_aligned
from .cache import Cache
from .errors import BireadError
from .llm.embed import OLLAMA_BASE, Embedder
from .render import Download, download_name
from .shelf import by_slug, load_pair
from .targets import get_target

ROOT = Path(__file__).resolve().parent.parent
BOOKS = ROOT / "web" / "books"
MANIFEST = BOOKS / "published.json"

#: Free, local, and good at this: BGE-M3 is multilingual, which is the whole
#: requirement — the two editions are matched in one shared space.
DEFAULT_EMBED_LOCAL = "bge-m3"
DEFAULT_EMBED_CLOUD = "openai/text-embedding-3-large"


@dataclass
class Made:
    """A book built but not yet vouched for."""
    slug: str
    title: str
    path: Path
    paragraphs: int
    blank: int
    glossed: int
    #: How much of the English that exists ended up on the page. None where the
    #: alignment could not say.
    placed_share: float | None = None

    @property
    def coverage(self) -> float:
        return 1.0 - (self.blank / self.paragraphs) if self.paragraphs else 0.0


def read_manifest() -> dict:
    if not MANIFEST.is_file():
        return {"books": []}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def write_manifest(manifest: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def approve(slug: str, file: str, english: str | None, today: str) -> dict:
    """Add a book to the shelf, or update what is said about one already there."""
    manifest = read_manifest()
    row = {"slug": slug, "file": file, "english": english, "approved": today}
    books = [b for b in manifest["books"] if b["slug"] != slug]
    manifest["books"] = books + [row]
    write_manifest(manifest)
    return row


def add_formats(slug: str, formats: list[str], books_dir: Path | None = None,
                remake: bool = False, on_book=None) -> list[tuple[str, list[Download]]]:
    """Typeset published books into EPUB (and PDF), and put them inside.

    A reader downloads the book as one file, so the formats live in it rather
    than beside it. `slug` is one book or "all"; "all" means every book on the
    shelf, which is what keeps them from drifting apart — a format everywhere is
    a promise the whole shelf has to keep, not a thing one book happens to have.

    Nothing is fetched and nothing is charged. The book on disk is the source.

    A format the book already carries is left alone, so this can be re-run over
    the whole shelf for the cost of the books that are actually missing one. The
    book's *text* cannot go stale that way — `make` writes a fresh file carrying
    no formats at all — but the *typesetting* can, and did: Micromégas was the
    one book with an EPUB and it was the reflowable one, built before that design
    was reverted for the fixed-layout spread. A file carries no record of the
    exporter that made it, so `remake` is the answer rather than a guess: it is
    asked for by whoever changed the exporter, who is the only one who knows.
    """
    from .export.refit import formats_from_html
    from .render import BOOK_DATA_RE, add_downloads

    books = books_dir or BOOKS
    rows = read_manifest()["books"]
    if slug != "all":
        rows = [row for row in rows if row["slug"] == slug]
        if not rows:
            raise BireadError(
                f"{slug!r} is not a published book — `--formats` acts on a book "
                f"that is already on the shelf. Published: "
                f"{', '.join(r['slug'] for r in read_manifest()['books']) or 'none'}")

    made: list[tuple[str, list[Download]]] = []
    for row in rows:
        path = books / row["file"]
        if not path.is_file():
            raise BireadError(f"published book {row['slug']!r} has no file at {path}")
        html = path.read_text(encoding="utf-8")
        found = BOOK_DATA_RE.search(html)
        if not found:
            raise BireadError(f"{path} is not a built book: it carries no book data")
        carried = {entry["format"] for entry in json.loads(found.group(2)).get("downloads") or []}
        wanted = [fmt for fmt in formats if remake or fmt not in carried]

        book = by_slug(row["slug"])
        downloads: list[Download] = []
        if wanted:
            with tempfile.TemporaryDirectory() as tmp:
                # The author is the one thing a finished book does not say about
                # itself, and the shelf does.
                downloads = formats_from_html(html, Path(tmp), wanted,
                                              author=book.author if book else "")
            path.write_text(add_downloads(html, downloads), encoding="utf-8")
        made.append((row["slug"], downloads))
        if on_book:
            on_book(row["slug"], downloads, path)
    return made


def make(slug: str, *, translation: int = 0, gloss: bool = False,
         embedder=None, gloss_client=None, gloss_cfg=None,
         fetch=None, out_dir: Path | None = None, on_progress=None) -> Made:
    """Fetch both editions, match them by meaning, and write the finished book.

    Everything the terminal reports afterwards is measured off what was made, not
    predicted before it: a book that came out thin says so here rather than in
    front of a reader.
    """
    book = by_slug(slug)
    if book is None:
        raise BireadError(f"no book on the shelf called {slug!r}")

    original, published, _info = load_pair(book, translation, fetch, on_progress)
    result = build_aligned(
        title=book.title,
        chapters=original,
        published_chapters=published,
        embed=embedder.embed,
        target=get_target("english"),
        gloss=gloss,
        gloss_client=gloss_client,
        gloss_cache=Cache(None),
        gloss_cfg=gloss_cfg,
        on_progress=on_progress,
    )

    out = (out_dir or BOOKS) / f"{slug}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result.html, encoding="utf-8")

    report = result.alignment
    return Made(
        slug=slug,
        title=book.title,
        path=out,
        paragraphs=report.total if report else 0,
        blank=report.unmatched if report else 0,
        glossed=result.gloss.glossed if result.gloss else 0,
        placed_share=report.placed_share if report else None,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m biread.publish",
        description="Build a shelf book and, once you have looked at it, publish it.",
    )
    parser.add_argument(
        "slug",
        help="which shelf book (see python -m biread.shelf); \"all\" with --formats")
    parser.add_argument(
        "--formats", nargs="*", default=None, metavar="FORMAT",
        choices=["epub", "pdf"],
        help="typeset a book already on the shelf into EPUB (and pdf, if you ask "
             "for it) and put the files inside it. Makes nothing else and calls "
             "nothing; default: epub")
    parser.add_argument(
        "--remake", action="store_true",
        help="with --formats, typeset again even where the book already carries "
             "the format. For when the exporter itself has changed")
    parser.add_argument(
        "--translation", type=int, default=0, metavar="N",
        help="which English edition, where the shelf lists more than one (default: 0)")
    parser.add_argument(
        "--gloss", action="store_true",
        help="add hover glosses. Costs about four times the alignment; without it "
             "a reader adds them as they read, on their own key")
    parser.add_argument(
        "--approve", action="store_true",
        help="put the book on the shelf. Only after you have read the three "
             "places the check reports")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="say what it would fetch and cost, and call nothing")
    parser.add_argument(
        "--local", action="store_true",
        help=f"embed on a local Ollama ({OLLAMA_BASE}) instead of a cloud model — free")
    parser.add_argument("--embed-model", default=None, help="override the embedding model")
    parser.add_argument(
        "--english", default=None,
        help="how the card should name this English edition; defaults to what the "
             "shelf already says")
    parser.add_argument(
        "--no-check", action="store_true",
        help="skip the three-place look. Only sensible when re-making a book you "
             "have already read")
    return parser


def embedder_for(args) -> Embedder:
    from .config import load_config

    if args.local:
        return Embedder(args.embed_model or DEFAULT_EMBED_LOCAL, "", OLLAMA_BASE)
    cfg = load_config(require_key=True)
    return Embedder(
        args.embed_model or DEFAULT_EMBED_CLOUD,
        cfg.api_key or "",
        cfg.base_url or "https://openrouter.ai/api/v1",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.formats is not None:
        try:
            add_formats(args.slug, args.formats or ["epub"], remake=args.remake,
                        on_book=report_formats)
        except BireadError as exc:
            print(f"\n{exc}", file=sys.stderr)
            return 1
        print("\nRun `python web/build.py` to serve them.")
        return 0

    book = by_slug(args.slug)
    if book is None:
        print(f"No book on the shelf called {args.slug!r}. "
              f"Run `python -m biread.shelf` to see them.", file=sys.stderr)
        return 2

    version = book.translations[args.translation]
    if args.dry_run:
        print(f"{book.title} — {book.author}")
        print(f"  French   {book.page}")
        print(f"  English  {version.page}  ({version.label})")
        print(f"  {book.paragraphs:,} paragraphs, {book.chars:,} characters, "
              f"about {book.minutes} min to fetch and match")
        print("\nNothing was called. Drop --dry-run to make it.")
        return 0

    embedder = embedder_for(args)
    gloss_client = gloss_cfg = None
    if args.gloss:
        from .config import load_config
        from .llm import make_client

        cfg = load_config(require_key=True).for_glossing()
        gloss_cfg, gloss_client = cfg, make_client(cfg)

    def progress(stage, done, total):
        print(f"\r  {stage}: {done}/{total}", end="", flush=True)

    try:
        made = make(args.slug, translation=args.translation, gloss=args.gloss,
                    embedder=embedder, gloss_client=gloss_client, gloss_cfg=gloss_cfg,
                    on_progress=progress)
    except BireadError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    print()

    report_made(made)
    if not args.no_check:
        if not report_check(made):
            print("\nNot approved: fix what the check found, or look yourself and "
                  "re-run with --approve.")
            return 1

    if args.approve:
        from datetime import date

        row = approve(args.slug, made.path.name, args.english or version.label,
                      date.today().isoformat())
        print(f"\nOn the shelf: {row['slug']} — {row['english']}")
        print("Run `python web/build.py` to put it in the bundle.")
    else:
        print("\nNot on the shelf yet. Look at the three spreads above, then:")
        print(f"  python -m biread.publish {args.slug} --approve")
    return 0


def report_formats(slug: str, downloads: list[Download], path: Path) -> None:
    if not downloads:
        print(f"{slug}: already carries it, left alone")
        return
    files = ", ".join(f"{fmt.upper()} {len(blob) / 1e6:.1f} MB"
                      for fmt, _source, _filename, blob in downloads)
    print(f"{slug}: {files} — the book is now {path.stat().st_size / 1e6:.1f} MB")


def report_made(made: Made) -> None:
    print(f"{made.title} -> {made.path}")
    print(f"  {made.paragraphs:,} paragraphs, {round(made.coverage * 100)}% with an "
          f"English counterpart")
    if made.blank:
        print(f"  {made.blank:,} left blank — the French has no counterpart there")
    # The figure above says how much of the *French* is faced. On its own it
    # cannot tell a translator who condensed from an aligner that lost its way,
    # and those want opposite responses: ship it, or fix it.
    if made.placed_share is not None:
        placed = round(made.placed_share * 100)
        print(f"  {placed}% of the English that exists is on the page", end="")
        if placed >= 95:
            print(" — all of it; this translation is simply shorter")
        elif placed >= 80:
            print(" — most of it")
        else:
            print(f", and {100 - placed}% went nowhere. Look before believing the "
                  "blanks are the translator's doing")
    print(f"  {made.glossed:,} glossed" if made.glossed
          else "  no glosses — a reader adds them as they read, on their own key")


def report_check(made: Made) -> bool:
    """The bar, applied: opening, a middle chapter, the end."""
    from .check import spot_check

    try:
        found = spot_check(made.path)
    except BireadError as exc:
        print(f"  could not look at it: {exc}")
        return True   # a missing browser is not a fault in the book
    for spread in found.spreads:
        print(f"  spread {spread.index}/{found.total}: {spread.summary}")
    if found.faults:
        print("\nWhat the check found:")
        for fault in found.faults:
            print(f"  - {fault}")
    print(f"\n  screenshots: {found.shots_dir}")
    return not found.faults


if __name__ == "__main__":
    raise SystemExit(main())
