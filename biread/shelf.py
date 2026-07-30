"""The shelf: books that arrive without the reader bringing a file.

Every entry names two pages on Wikisource and nothing else is stored — biread
holds page names, never text, so the shelf is a list of links and the reader's
own browser fetches the book. The counts here were measured against the live
wiki on the date below, so a card can say how long a build takes before anything
is fetched; they are refreshed by `python -m biread.shelf --check`.

A book is on the shelf because somebody looked at it, not because it resolved.
That is the whole difference between this and a search box: the four extraction
faults that made the shelf curated were each found by reading a rendered page.
So an entry says plainly whether it has been read through, and one that has not
is not dressed up as one that has.
"""
from __future__ import annotations

from dataclasses import dataclass

MEASURED = "2026-07-30"

# Both editions are embedded before they are matched, and the pace is the
# network's, not the model's: Madame Bovary's 5,449 paragraphs took about
# fourteen minutes end to end in the spike this was measured from.
PARAGRAPHS_PER_MINUTE = 390


@dataclass(frozen=True)
class Translation:
    """One English edition of a work, as the wiki names it."""
    page: str
    translator: str | None = None
    year: str | None = None
    chapters: int = 0
    paragraphs: int = 0
    chars: int = 0
    abridged: bool = False
    chaptered: bool = True

    @property
    def label(self) -> str:
        bits = [b for b in (self.translator, self.year) if b]
        return " · ".join(bits) or self.page.rsplit("/", 1)[-1]


@dataclass(frozen=True)
class Book:
    slug: str
    title: str
    author: str
    page: str                       # the French work, as a Wikisource page name
    chapters: int
    paragraphs: int
    chars: int
    translations: tuple[Translation, ...]
    note: str
    read_through: bool = False
    coverage: float | None = None   # measured, where anyone has measured it
    lang: str = "fr"
    other: str = "en"
    added: bool = False             # brought in from the lookup screen, unchecked

    @property
    def translation(self) -> Translation:
        return self.translations[0]

    @property
    def minutes(self) -> int:
        total = self.paragraphs + self.translation.paragraphs
        return max(1, round(total / PARAGRAPHS_PER_MINUTE))

    @property
    def tokens(self) -> int:
        """What an embedding model is asked to read: both editions, once."""
        return round((self.chars + self.translation.chars) / 4)

    def as_dict(self) -> dict:
        t = self.translation
        return {
            "slug": self.slug, "title": self.title, "author": self.author,
            "page": self.page, "lang": self.lang, "other": self.other,
            "chapters": self.chapters, "paragraphs": self.paragraphs,
            "minutes": self.minutes, "tokens": self.tokens,
            "note": self.note, "readThrough": self.read_through,
            "coverage": self.coverage, "added": self.added,
            "english": t.label, "abridged": t.abridged, "chaptered": t.chaptered,
            "counts": [self.chapters, t.chapters],
            "translations": [
                {"page": x.page, "label": x.label, "chapters": x.chapters}
                for x in self.translations
            ],
        }


SHELF: tuple[Book, ...] = (
    Book(
        slug="candide",
        title="Candide, ou l’Optimisme",
        author="Voltaire",
        page="Candide, ou l’Optimisme",
        chapters=30, paragraphs=469, chars=184_197,
        translations=(
            Translation("Candide", "Smollett", "1920", 30, 689, 199_468),
        ),
        note="Smollett put this into English in Voltaire’s own century, and it "
             "still reads of that century — much of the pleasure of the facing page.",
        read_through=True, coverage=0.989,
    ),
    Book(
        slug="bovary",
        title="Madame Bovary",
        author="Flaubert",
        page="Madame Bovary",
        chapters=35, paragraphs=2_840, chars=676_154,
        translations=(
            Translation("Madame Bovary (Marx-Aveling translation)",
                        "Marx-Aveling", "1886", 35, 2_609, 641_890),
        ),
        note="The two editions break their dialogue differently, so a few hundred "
             "short retorts face an empty space. The book itself is whole.",
        read_through=True, coverage=0.874,
    ),
    Book(
        slug="80days",
        title="Le Tour du monde en quatre-vingts jours",
        author="Verne",
        page="Le Tour du monde en quatre-vingts jours",
        chapters=37, paragraphs=1_892, chars=409_963,
        translations=(
            Translation("Around the World in Eighty Days (Towle)",
                        "Towle", "1873", 37, 1_538, 357_005, abridged=True),
            Translation("Works of Jules Verne/Round the World in Eighty Days",
                        None, "1911", 37, 1_656, 388_120),
        ),
        note="Towle cut as he went, so some of the French will face an empty page. "
             "A second English edition of 1911 is here too, its translator unnamed.",
    ),
    Book(
        slug="micromegas",
        title="Micromégas",
        author="Voltaire",
        page="Micromégas",
        chapters=7, paragraphs=74, chars=38_819,
        translations=(
            Translation("Micromegas (Phalen)", "Phalen", None, 7, 127, 40_431),
            Translation("The Works of Voltaire/Volume 3/Micromegas",
                        "Fleming", "1906", 1, 104, 41_705, chaptered=False),
        ),
        note="Two English versions, and they are shaped differently: Phalen’s "
             "follows the French chapter for chapter, Fleming’s 1906 runs as one "
             "piece, which pairs more loosely.",
    ),
    Book(
        slug="20000",
        title="Vingt mille lieues sous les mers",
        author="Verne",
        page="Vingt mille lieues sous les mers",
        chapters=47, paragraphs=3_404, chars=861_245,
        translations=(
            Translation("Works of Jules Verne/Twenty Thousand Leagues Under the Sea",
                        None, "1911", 46, 2_140, 581_572),
        ),
        note="The two editions count their chapters differently, 47 against 46. "
             "That is two editions, not an error, and the matching takes it in stride.",
    ),
)


def by_slug(slug: str) -> Book | None:
    return next((b for b in SHELF if b.slug == slug), None)


def search(query: str, books: tuple[Book, ...] = SHELF) -> list[Book]:
    """The shelf is read, not searched — so searching it only narrows what is here."""
    q = query.strip().lower()
    if not q:
        return list(books)
    return [b for b in books
            if q in b.title.lower() or q in b.author.lower()
            or any(q in t.label.lower() for t in b.translations)]


# The filters a shelf of this size can honestly offer. One that would match every
# book, or none, is not a filter; the page drops those rather than showing a
# control that does nothing.
FILTERS: dict[str, str] = {
    "read": "Read through",
    "whole": "Nothing abridged",
    "several": "More than one translation",
    "quick": "Under ten minutes",
}


def matches(book: Book, key: str) -> bool:
    if key == "read":
        return book.read_through
    if key == "whole":
        return not book.translation.abridged
    if key == "several":
        return len(book.translations) > 1
    if key == "quick":
        return book.minutes < 10
    return True


def catalogue(books: tuple[Book, ...] = SHELF) -> dict:
    """Everything the shelf screen draws, as plain data."""
    useful = [k for k in FILTERS if 0 < sum(matches(b, k) for b in books) < len(books)]
    return {
        "measured": MEASURED,
        "perMinute": PARAGRAPHS_PER_MINUTE,
        "filters": [{"key": k, "label": FILTERS[k],
                     "slugs": [b.slug for b in books if matches(b, k)]} for k in useful],
        "books": [b.as_dict() for b in books],
    }


def from_lookup(title: str, author: str | None, page: str, lang: str,
                translation: Translation, chapters: int, paragraphs: int,
                chars: int, other: str = "en") -> Book:
    """A book the reader found themselves. Buildable, and honestly unvouched for."""
    return Book(
        slug="found:" + page, title=title, author=author or "", page=page,
        chapters=chapters, paragraphs=paragraphs, chars=chars,
        translations=(translation,), lang=lang, other=other, added=True,
        note="Nobody has read this one through. It may pair well; we have not looked.",
    )


# --- fetching one -----------------------------------------------------------

def _side(edition, fallback_title: str, fallback_author: str | None) -> dict:
    """What an edition says about itself, in the shape the builder's cards read."""
    c = edition.credits
    return {
        "title": c.title or fallback_title,
        "author": c.translator or c.author or fallback_author,
        "language": edition.lang,
        "pages": None,
        "paragraphs": edition.paragraphs,
        "chars": edition.chars,
        "chapters": len(edition.chapters),
        "year": c.year,
        "shape": edition.shape,
        "resolved": edition.resolved,
    }


def load_pages(lang: str, page: str, other: str, other_page: str,
               fetch=None, on_progress=None, titles: tuple = (None, None, None)):
    """Both editions named by page, fetched and read into chapters.

    Returns the two chapter lists and what each edition says about itself. Only
    page names travel from here; the text is the wiki's and stays the reader's.
    """
    from biread import wikisource as ws

    fetch = fetch or ws.default_fetch
    step = on_progress or (lambda *a: None)
    title, author, translator = titles

    original = ws.load(lang, page, fetch, lambda i, t: step("fetch-orig", i, t))
    english = ws.load(other, other_page, fetch, lambda i, t: step("fetch-pub", i, t))
    info = {
        "orig": _side(original, title or page, author),
        "pub": _side(english, other_page.rsplit("/", 1)[-1], translator),
    }
    return ws.to_chapters(original), ws.to_chapters(english), info


def load_pair(book: Book, index: int = 0, fetch=None, on_progress=None):
    """Both editions of a shelf book, in the translation the reader chose."""
    t = book.translations[index]
    return load_pages(book.lang, book.page, book.other, t.page, fetch, on_progress,
                      (book.title, book.author, t.translator))


def probe(lang: str, page: str, other: str, other_page: str, fetch=None) -> dict:
    """What the two pages turn out to be, without fetching a chapter of either.

    Enough to say whether a book found by searching can be built at all, and how
    nearly the two editions agree — which is what the lookup screen reports.
    """
    from biread import wikisource as ws

    fetch = fetch or ws.default_fetch
    found = ws.resolve(lang, page, fetch)
    counterpart = ws.resolve(other, other_page, fetch)
    theirs = ws.credits(counterpart.html)
    return {
        "page": page, "otherPage": other_page,
        "chapters": len(found.pages), "otherChapters": len(counterpart.pages),
        "shape": found.shape, "otherShape": counterpart.shape,
        "author": ws.credits(found.html).author,
        "english": theirs.edition, "translator": theirs.translator, "year": theirs.year,
        "buildable": bool(found.pages and counterpart.pages),
    }


# --- keeping the numbers honest ---------------------------------------------

def check(fetch=None) -> list[str]:
    """Re-measure every entry against the live wiki. Reports what has drifted."""
    from biread import wikisource as ws

    fetch = fetch or ws.default_fetch
    drift = []
    for book in SHELF:
        for index, translation in enumerate(book.translations):
            _, _, info = load_pair(book, index, fetch)
            recorded = [("chapters", book.chapters, info["orig"]["chapters"]),
                        ("paragraphs", book.paragraphs, info["orig"]["paragraphs"]),
                        ("chars", book.chars, info["orig"]["chars"])] if index == 0 else []
            recorded += [
                (f"English[{index}] chapters", translation.chapters, info["pub"]["chapters"]),
                (f"English[{index}] paragraphs", translation.paragraphs, info["pub"]["paragraphs"]),
                (f"English[{index}] chars", translation.chars, info["pub"]["chars"]),
            ]
            for what, was, now in recorded:
                if was != now:
                    drift.append(f"{book.slug}: {what} {was} -> {now}")
    return drift


if __name__ == "__main__":  # pragma: no cover - a maintenance errand, not a test
    import sys

    if "--check" not in sys.argv:
        for b in SHELF:
            print(f"{b.slug:<12} {b.title[:38]:<40} {b.chapters:>3} ch  "
                  f"~{b.minutes} min  {b.translation.label}")
        raise SystemExit
    print(f"measured {MEASURED}; re-reading {len(SHELF)} books…")
    for line in check() or ["nothing has moved"]:
        print(" ", line)
