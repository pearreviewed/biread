"""Standard Ebooks as a second source for the published column.

English only, so it never supplies the original — but it carries translations
Wikisource does not have at all (Salammbô) and others Wikisource holds in a shape
that will not align (Les Misérables, 411 sections against the translation's 48).
Where both sources have a work, Wikisource is preferred: it is the only one that
can supply both halves, and a book read from one source is one thing to verify.

Structure is read from the file's own EPUB semantics — `epub:type="bodymatter
chapter"` marks the body, so front and back matter drop out by declaration
rather than by guesswork. That is the same principle as Wikisource's
`ws-noexport`, in a different vocabulary, and it is why neither source needs a
rule about what a title page looks like.

The translator is in the URL (`/salammbo/j-s-chartres`), so a search result
already knows who translated it and a card costs no second request.

Nothing here opens a socket by itself: every entry point takes a `fetch`, so the
browser can pass its own.
"""
from __future__ import annotations

import re
import unicodedata
import urllib.parse
from dataclasses import dataclass
from html.parser import HTMLParser

from .wikisource import Fetch, default_fetch

BASE = "https://standardebooks.org"

_SKIP_TAGS = {"script", "style", "head", "figure", "table"}
_VOID = {"br", "img", "link", "meta", "hr", "input", "source", "col"}

#: A work's path, with the translator as an optional third segment.
_EBOOK_HREF = re.compile(r'href="(/ebooks/[a-z0-9\'-]+/[a-z0-9\'-]+(?:/[a-z0-9\'-]+)?)"')


def search_url(query: str) -> str:
    return f"{BASE}/ebooks?{urllib.parse.urlencode({'query': query})}"


def text_url(path: str) -> str:
    return f"{BASE}{path}/text/single-page"


def _titlecase(slug: str) -> str:
    return " ".join(word.capitalize() for word in slug.split("-"))


@dataclass(frozen=True)
class Book:
    """One edition, as the site's own URL names it."""
    path: str
    author: str
    title: str
    translator: str | None = None

    @property
    def label(self) -> str:
        return f"{self.title} · {self.translator}" if self.translator else self.title


def search(query: str, fetch: Fetch = default_fetch, limit: int = 8) -> list[Book]:
    """Works matching a query.

    A third path segment names the translator; two segments mean none is
    credited. That is *not* evidence the book was written in English — Zola's
    Doctor Pascal is plainly a translation and carries two — so an uncredited
    edition is reported without a translator rather than as an original.
    """
    page = fetch(search_url(query))
    seen: set[str] = set()
    found: list[Book] = []
    for path in _EBOOK_HREF.findall(page):
        if path in seen:
            continue
        seen.add(path)
        parts = path.strip("/").split("/")[1:]
        translator = _titlecase(parts[2]) if len(parts) > 2 else None
        found.append(Book(path, _titlecase(parts[0]), _titlecase(parts[1]), translator))
        if len(found) >= limit:
            break
    return found


def _fold(name: str) -> str:
    """A name with its accents and case set aside, for comparing only.

    The site spells its authors in URL slugs (`emile-zola`) and Wikisource spells
    them as they are written (`Émile Zola`). Those are the same author, and the
    difference is an artefact of what a URL may contain.
    """
    bare = unicodedata.normalize("NFKD", name or "")
    bare = "".join(c for c in bare if not unicodedata.combining(c))
    return " ".join(bare.casefold().replace("-", " ").split())


def by_author(author: str, fetch: Fetch = default_fetch, limit: int = 8) -> list[Book]:
    """This author's editions here, and nobody else's.

    A search for a title alone is too loose to trust — "germinal" also returns
    Voltairine de Cleyre's poetry — so the author is what the results are held
    to. Where the site names a different author it is a different book, and an
    empty list is the right answer: these are offered to a reader to confirm,
    never asserted, and offering the wrong book wastes the one judgement we are
    relying on.
    """
    if not author:
        return []
    want = _fold(author)
    return [b for b in search(author, fetch, limit=limit * 3) if _fold(b.author) == want][:limit]


class _Body(HTMLParser):
    """Paragraphs of the bodymatter chapters, one bucket per chapter."""

    #: What the site calls a group of chapters. A work divided this way can be
    #: read at either grain, and which one is right depends on the other edition.
    _division_words = {"part", "volume", "division", "book"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chapters: list[dict] = []
        self._stack: list[tuple[bool, bool]] = []   # skips, opened a chapter
        self._skip = 0
        self._depth = 0
        self._division = 0
        self._para: list[str] | None = None
        self._heading: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _VOID:
            return
        attributes = dict(attrs)
        kind = attributes.get("epub:type", "").split()
        # "chapter" alone, not "bodymatter chapter": a book divided into parts
        # (Les Misérables has 48) carries bodymatter on the outer division and
        # chapter on the 365 sections inside it. Nothing in the front or back
        # matter is ever a chapter, so the one word is enough to tell them apart.
        opened = tag == "section" and "chapter" in kind
        if tag == "section" and not opened and self._division_words & set(kind):
            self._division += 1
        if opened:
            # The id is the chapter's address in the work — "chapter-1-1-1"
            # through "chapter-5-9-6" for Les Misérables. Two editions of a book
            # in parts can only be paired reliably on addresses like these: read
            # as a flat run, one chapter missing from either side shifts every
            # pairing after it, and the drift is silent.
            self.chapters.append(
                {"number": str(len(self.chapters) + 1), "title": None,
                 "id": attributes.get("id"), "division": self._division,
                 "paragraphs": []})
            self._depth += 1
        skips = tag in _SKIP_TAGS
        self._stack.append((skips, opened))
        if skips:
            self._skip += 1
        elif self._depth and tag == "p" and self._para is None:
            self._para = []
        elif self._depth and tag in ("h2", "h3") and self._heading is None:
            self._heading = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID or not self._stack:
            return
        if tag == "p" and self._para is not None:
            text = re.sub(r"\s+", " ", "".join(self._para)).strip()
            if len(text) > 20 and self.chapters:
                self.chapters[-1]["paragraphs"].append(text)
            self._para = None
        if tag in ("h2", "h3") and self._heading is not None:
            text = re.sub(r"\s+", " ", "".join(self._heading)).strip()
            if text and self.chapters and not self.chapters[-1]["title"]:
                self.chapters[-1]["title"] = text
            self._heading = None
        skips, opened = self._stack.pop()
        if skips:
            self._skip -= 1
        if opened:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._heading is not None:
            self._heading.append(data)
        elif self._para is not None:
            self._para.append(data)


#: "chapter-5-9-6" -> (5, 9, 6). The work's own coordinates, not our count.
_ADDRESS = re.compile(r"(\d+)")


def address(chapter: dict) -> tuple[int, ...] | None:
    """Where a chapter sits in a work divided into parts, as the file says."""
    numbers = _ADDRESS.findall(chapter.get("id") or "")
    return tuple(int(n) for n in numbers) if numbers else None


def by_division(chapters: list[dict]) -> list[dict]:
    """The same book read one grain coarser, a chapter per division.

    Some editions divide a work where the other numbers it: French Notre-Dame
    puts each of its eleven books on one page, while this edition gives the
    fifty-nine chapters inside them. Read at the division, the two are eleven
    against eleven — and a pairing the two editions agree on beats a finer one
    they do not.
    """
    grouped: list[dict] = []
    for chapter in chapters:
        if not grouped or chapter.get("division") != grouped[-1]["division"]:
            grouped.append({"number": str(len(grouped) + 1), "title": chapter["title"],
                            "division": chapter.get("division"), "paragraphs": []})
        grouped[-1]["paragraphs"] += chapter["paragraphs"]
    return grouped


def parse(page_html: str, divisions: bool = False) -> list[dict]:
    """The chapters of a single-page edition, or its divisions."""
    body = _Body()
    body.feed(page_html)
    chapters = [c for c in body.chapters if c["paragraphs"]]
    return by_division(chapters) if divisions else chapters


def load(path: str, fetch: Fetch = default_fetch, divisions: bool = False) -> list[dict]:
    """Chapters of one edition, given /ebooks/author/title[/translator]."""
    return parse(fetch(text_url(path)), divisions=divisions)
