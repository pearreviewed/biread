"""An EPUB or a PDF made from a book that is already finished.

The exporters take the book the pipeline holds in memory — chapters and their
translation — which is fine while a book is being built and useless afterwards.
A shelf book is fetched, matched and rendered once; asking for its EPUB a month
later must not mean fetching both editions and matching them again, paying for
work already done and correct.

So the book is read back out of its own file. That is the same move `rewrap`
makes for the reader, and it holds for the same reason: everything the exporters
need is on the page. `book_from_html` is checked against the file it came from —
re-deriving the pairs and the chapter headings from it lands on what the book
already carries, to the paragraph.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..cleanup import Chapter
from ..errors import BireadError
from ..render import BOOK_DATA_RE, Download, download_name
from ..targets import ENGLISH, TARGETS, Target
from ..translate import hash_text
from .epub import write_epub
from .pdf import write_pdf

#: What `build_book_data` writes above every chapter, on the French side.
FR_EYEBROW_RE = re.compile(r"^Chapitre\s+(.+)$")

WRITERS = {"epub": write_epub, "pdf": write_pdf}


def book_from_html(html: str) -> tuple[str, list[Chapter], dict[str, str], Target]:
    """A finished book, read back into the shape the exporters take.

    The chapter's number is taken from the eyebrow the book prints rather than
    from the source's own numbering token, because that eyebrow is what a reader
    saw and what the exports must agree with: an edition writing "Chapitre
    premier" is already a numeral on the page by the time it is in the file.
    """
    found = BOOK_DATA_RE.search(html)
    if not found:
        raise BireadError("not a built book: it carries no book data")
    data = json.loads(found.group(2))

    target = next((t for t in TARGETS.values() if t.code == data.get("lang")), ENGLISH)
    pairs = data["pairs"]
    starts = [meta["pair"] for meta in data.get("chapters") or []]

    translations = {hash_text(pair["fr"]): pair.get("en", "") for pair in pairs}
    chapters: list[Chapter] = []
    # Anything standing before the first chapter is the book's own leading
    # section — a preface, a dedication — and it is numbered by nobody.
    if not starts or starts[0] > 0:
        head = pairs[:starts[0]] if starts else pairs
        if head:
            chapters.append(Chapter(None, None, [pair["fr"] for pair in head]))
    for meta, end in zip(data.get("chapters") or [], starts[1:] + [len(pairs)]):
        eyebrow = FR_EYEBROW_RE.match(meta["frEyebrow"] or "")
        title = meta.get("frTitle") or None
        if title:
            translations[hash_text(title)] = meta.get("enTitle") or ""
        chapters.append(Chapter(
            number=eyebrow.group(1) if eyebrow else (meta["frEyebrow"] or None),
            title=title,
            paragraphs=[pair["fr"] for pair in pairs[meta["pair"]:end]],
        ))
    return data["titleFr"], chapters, translations, target


def formats_from_html(html: str, out_dir: Path, formats: list[str],
                      author: str = "") -> list[Download]:
    """Typeset a finished book into the formats asked for, and hand back what a
    reader downloads: the file's own name and its bytes, ready to go inside the
    book. Nothing is called and nothing is charged; both exporters only measure
    type in a headless browser.

    The saved file is named after the book's own title rather than anything the
    caller knows, for the same reason the rest of this module reads the file: the
    book is the source, and a shelf record naming it differently would put a name
    on a reader's disk that the book itself does not use.
    """
    title, chapters, translations, target = book_from_html(html)
    name = download_name(title)
    out_dir.mkdir(parents=True, exist_ok=True)

    made: list[Download] = []
    for fmt in formats:
        write = WRITERS.get(fmt)
        if write is None:
            raise BireadError(f"no exporter for {fmt!r}; there is "
                              f"{' and '.join(sorted(WRITERS))}")
        path = out_dir / f"{name}.{fmt}"
        write(title, chapters, translations, path, target, author)
        made.append((fmt, "translation", path.name, path.read_bytes()))
    return made
