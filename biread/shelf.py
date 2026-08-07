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
    """One English edition of a work, as its library names it.

    `page` is a Wikisource page name, or a Standard Ebooks path when `source`
    says so — three of the shelf's books take their French from the wiki and
    their English from the other library, because the wiki has no usable copy.
    """
    page: str
    translator: str | None = None
    year: str | None = None
    chapters: int = 0
    paragraphs: int = 0
    chars: int = 0
    abridged: bool = False
    chaptered: bool = True
    source: str = "wikisource"
    divisions: bool = False   # read at the division where the French is a book

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
    #: What the book is, in one sentence that stands on its own — the line every
    #: card shows on its face, where a reader chooses. One sentence because two
    #: sizes a card by its longest blurb rather than by its book.
    lead: str = ""
    #: The rest of it, for the drawer that opens under the pointer. Written here
    #: rather than fetched: a curated shelf is one somebody has read, and an
    #: encyclopaedia's opening line is as often about an edition's publication
    #: history as about the story. A book a reader looked up carries neither, so
    #: its card says nothing it has not earned and does not open.
    summary: str = ""
    read_through: bool = False
    coverage: float | None = None   # measured, where anyone has measured it
    lang: str = "fr"
    other: str = "en"
    added: bool = False             # brought in from the lookup screen, unchecked
    #: Sections of the work's own wiki page that are not the work — an editor's
    #: notice, a list of sources, textual variants. Named because nothing on the
    #: page distinguishes them: they sit among the chapters, under names of their
    #: own, and every one of them calls itself "book" in its header.
    skip: tuple[str, ...] = ()

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
            "note": self.note, "lead": self.lead, "summary": self.summary,
            "readThrough": self.read_through,
            "coverage": self.coverage, "added": self.added,
            "english": t.label, "abridged": t.abridged, "chaptered": t.chaptered,
            "counts": [self.chapters, t.chapters], "source": t.source,
            # Abridgement travels with the translation, not with the book: 80 Days
            # is cut in Towle and whole in the 1911, so the card must be able to
            # stop saying it when the reader switches edition.
            "translations": [
                {"page": x.page, "label": x.label, "chapters": x.chapters,
                 "source": x.source, "abridged": x.abridged}
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
             "still reads of that century, which is much of the pleasure of the "
             "facing page.",
        lead="A young man taught this is the best of all possible worlds is "
             "thrown out into it.",
        summary="Voltaire’s answer to the philosophers who called this world the "
                "best one possible: the Lisbon earthquake, the Inquisition, "
                "Eldorado, one calamity a chapter, and a small farm outside "
                "Constantinople at the end of it, with a garden to tend.",
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
        lead="Emma Bovary lives beyond her means to escape the ennui of provincial "
             "life.",
        summary="A convent education on smuggled novels, a dull country health "
                "officer for a husband, and a town Flaubert set down entire – its "
                "chemist, its priest, its gossip – under the subtitle he gave it, "
                "Mœurs de province. Two lovers, debts her husband knows nothing "
                "about, and the draper who lent her the money at the end of them.",
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
        lead="Phileas Fogg wagers half his fortune that he can go round the world "
             "in eighty days.",
        summary="A man like a clock, crossing an empire the railways and steamers "
                "have only just made crossable: a new servant, a detective at Suez "
                "who is certain he has robbed the Bank of England, a widow carried "
                "off a pyre in India, and a day gained on the way home that nobody "
                "had counted.",
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
        lead="A traveller from Sirius, eight leagues tall, stops off at the Earth.",
        summary="One of the first stories in which the visitors come to us rather "
                "than we to them. He picks up a Saturnian on the way past, and "
                "finds the inhabitants of the Earth too small to see and quite "
                "sure they are the point of it all.",
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
        lead="Three men hunting a sea monster are taken prisoner by it.",
        summary="A professor, his servant and a harpooner aboard the Nautilus, "
                "whose captain shows them the whole ocean floor and never says "
                "who drove him under it. Verne first made him a Pole avenging his "
                "family on the Russians; the publisher refused it, and the rage "
                "survives without the reason.",
    ),
    Book(
        slug="lesmis",
        title="Les Misérables",
        author="Victor Hugo",
        page="Les Misérables",
        chapters=364, paragraphs=12_208, chars=3_025_187,
        translations=(
            Translation("/ebooks/victor-hugo/les-miserables/isabel-f-hapgood",
                        "Hapgood", "1887", 365, 12_192, 3_131_069,
                        source="standardebooks"),
        ),
        note="Three hundred and sixty-five chapters over five volumes, and the "
             "two editions agree on all but two of them. The longest book here "
             "by some way, so set it going and come back to it.",
        lead="Five years for a stolen loaf, fourteen for trying to escape, and a "
             "life outrunning both.",
        summary="Jean Valjean, and the bishop’s candlesticks that turn him: a "
                "factory, a child bought back from an inn, a policeman who cannot "
                "let a freed man stay free, and a barricade in the Paris of 1832 "
                "that the boys behind it do not come down from. Hugo stops for "
                "Waterloo, the sewers and the argot of thieves on the way.",
        read_through=True, coverage=0.921,
    ),
    Book(
        slug="notredame",
        title="Notre-Dame de Paris",
        author="Victor Hugo",
        page="Notre-Dame de Paris",
        chapters=11, paragraphs=4_116, chars=1_009_855,
        translations=(
            Translation("/ebooks/victor-hugo/notre-dame-de-paris/isabel-f-hapgood",
                        "Hapgood", "1888", 11, 3_799, 1_025_227,
                        source="standardebooks", divisions=True),
        ),
        note="The wiki puts each of Hugo’s eleven books on one page where this "
             "translation gives the fifty-nine chapters inside them, so the two "
             "are read at the grain they agree on: eleven against eleven.",
        lead="Paris in 1482, told from the cathedral down.",
        summary="An archdeacon who can no longer pray, a captain who means "
                "nothing by it, the dancer they destroy between them, and the "
                "deaf bellringer who is the only one who tries to save her. Hugo "
                "wrote it to stop Paris pulling its Gothic down, and named it for "
                "the building rather than the man.",
        read_through=True, coverage=0.861,
    ),
)
# Salammbô stood here and is off the shelf for now. Its record is whole in the
# history — the wiki page, the Chartres translation, and the skip list naming
# the edition's apparatus — so putting it back is restoring one Book, not
# working it out again. Its built file stays in web/books/, unlisted.


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
#
# There was a "Nothing abridged" here and it is gone. It hid exactly one book,
# and it hid the wrong thing about it: it judged only the default translation,
# so 80 Days disappeared although the unabridged 1911 edition of it is on the
# card and choosable. The fact keeps its place on the card, where it is about a
# translation and not about a book.
FILTERS: dict[str, str] = {
    "read": "Read through",
    "several": "More than one translation",
    "quick": "Builds in under ten minutes",
}


def matches(book: Book, key: str) -> bool:
    if key == "read":
        return book.read_through
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


def _english_side(chapters: list[dict], path: str, translator: str | None) -> dict:
    """What a Standard Ebooks edition says about itself, in the same shape.

    It has no page-by-page structure to report, so `shape` says where it came
    from rather than pretending to a wiki shape it does not have.
    """
    return {
        "title": path.rsplit("/", 2)[1].replace("-", " ").title(),
        "author": translator, "language": "en", "pages": None,
        "paragraphs": sum(len(c["paragraphs"]) for c in chapters),
        "chars": sum(len(p) for c in chapters for p in c["paragraphs"]),
        "chapters": len(chapters), "year": None,
        "shape": "standardebooks", "resolved": path,
    }


def load_pages(lang: str, page: str, other: str, other_page: str,
               fetch=None, on_progress=None, titles: tuple = (None, None, None),
               translation: Translation | None = None, skip: tuple[str, ...] = ()):
    """Both editions named by page, fetched and read into chapters.

    Returns the two chapter lists and what each edition says about itself. Only
    page names travel from here; the text is the library's and stays the
    reader's. The original is always the wiki's — no other French source lets a
    browser fetch it — but the English may come from the second library.
    """
    from biread import wikisource as ws

    fetch = fetch or ws.default_fetch
    step = on_progress or (lambda *a: None)
    title, author, translator = titles

    original = ws.load(lang, page, fetch, lambda i, t: step("fetch-orig", i, t),
                       skip=skip)
    if translation is not None and translation.source == "standardebooks":
        from biread import standardebooks as se

        step("fetch-pub", 0, 1)
        chapters = se.load(other_page, fetch, divisions=translation.divisions)
        step("fetch-pub", 1, 1)
        info = {"orig": _side(original, title or page, author),
                "pub": _english_side(chapters, other_page, translator)}
        return ws.to_chapters(original), _as_chapters(chapters), info

    english = ws.load(other, other_page, fetch, lambda i, t: step("fetch-pub", i, t))
    info = {
        "orig": _side(original, title or page, author),
        "pub": _side(english, other_page.rsplit("/", 1)[-1], translator),
    }
    return ws.to_chapters(original), ws.to_chapters(english), info


def _as_chapters(rows: list[dict]):
    from biread.cleanup import Chapter

    return [Chapter(number=r["number"], title=r.get("title"), paragraphs=r["paragraphs"])
            for r in rows]


def load_pair(book: Book, index: int = 0, fetch=None, on_progress=None):
    """Both editions of a shelf book, in the translation the reader chose."""
    t = book.translations[index]
    return load_pages(book.lang, book.page, book.other, t.page, fetch, on_progress,
                      (book.title, book.author, t.translator), translation=t,
                      skip=book.skip)


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


def probe_alone(lang: str, page: str, fetch=None) -> dict:
    """What the original is, when the wiki named nothing to face it.

    Wikisource's interwiki links are sparse — Germinal and Candide both carry
    none, though English editions of both exist — so "no counterpart" is a fact
    about the link, not about the book. The second library can be asked instead,
    and the question it answers is whose book this is: English-only, so it
    supplies the facing page and never the original.
    """
    from biread import wikisource as ws

    found = ws.resolve(lang, page, fetch or ws.default_fetch)
    return {
        "page": page, "chapters": len(found.pages), "shape": found.shape,
        "author": ws.credits(found.html).author, "buildable": bool(found.pages),
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
