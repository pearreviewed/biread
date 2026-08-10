import pytest
from biread.build import build_aligned, build_reader
from biread.cache import Cache
from biread.cleanup import Chapter
from biread.gloss import FIELD
from biread.llm.base import Completion
from biread.translate import flatten, hash_text


def body(book):
    return flatten(book[1:])  # build_reader trims the unnumbered preamble


def one_vector(texts):
    """Every text alike: enough for alignment to run, nothing to prove by it."""
    return [[1.0, 0.0] for _ in texts]


def by_section(texts):
    """Each section its own direction, so unnumbered divisions have something to
    pair on. The trailing digit is what a real embedder would read as topic."""
    def vector(text):
        digits = [c for c in text if c.isdigit()]
        vec = [0.0] * 8
        vec[int(digits[-1]) % 8 if digits else 7] = 1.0
        return vec
    return [vector(t) for t in texts]


@pytest.fixture
def published():
    return [
        Chapter("I", "The Departure", ["First paragraph.", "Second paragraph."]),
        Chapter("II", "The Arrival", ["Third paragraph."]),
    ]


@pytest.fixture
def gloss_reply():
    """One well-formed unit per body paragraph of the `book` fixture."""
    lines = []
    for number, first in enumerate(["Premier", "Deuxième", "Troisième"]):
        lines.append(f"@@@{number}@@@")
        lines.append(f" {FIELD} ".join([first, "adj.", "the first"]))
    return Completion("\n".join(lines), False)


def test_build_streams_the_translation_as_it_arrives(book, client, config):
    """The builder's progress screen fills its right-hand page with real prose
    while the book is still being translated."""
    seen = []
    build_reader(
        title="Micromégas", chapters=book, client=client, cache=Cache(None), cfg=config(),
        on_text=lambda pairs: seen.extend(pairs),
    )
    assert [french for french, _ in seen] == [u.text for u in body(book)]
    assert all(english for _, english in seen)


def test_build_without_a_text_callback_is_unchanged(book, client, config):
    result = build_reader(
        title="Micromégas", chapters=book, client=client, cache=Cache(None), cfg=config()
    )
    assert result.translation.translated == len(body(book))
    assert "Micromégas" in result.html


def test_an_aligned_book_can_still_be_glossed(book, published, config, make_client, gloss_reply):
    """The route that translates nothing was the one route with no hover. The
    published column stays the translator's, word for word; only the French is
    glossed."""
    result = build_aligned(
        title="Micromégas", chapters=book, published_chapters=published, embed=one_vector,
        gloss=True, gloss_client=make_client(script=[gloss_reply]), gloss_cfg=config(),
    )
    assert result.gloss.glossed == 3
    assert result.gloss.glosses[hash_text("Premier paragraphe.")][0].gloss == "the first"
    assert result.translation is None


def test_matching_streams_the_pairs_it_places(book, published):
    """The align route had nothing to hand its progress screen, so the spread was
    fed the French with an empty counterpart and the right page stayed blank for
    the whole run. Matching reports a chapter at a time, which is what its own
    counter is already counting."""
    seen = []
    build_aligned(
        title="Micromégas", chapters=book, published_chapters=published, embed=one_vector,
        on_text=lambda pairs: seen.extend(pairs),
    )
    assert [french for french, _ in seen] == [p for c in book[1:] for p in c.paragraphs]
    assert any(english for _, english in seen)


def test_a_dated_book_heads_both_pages_from_the_two_editions():
    """A diary is divided and numbered by nothing, and requiring a number left La
    Nausée with no headings at all. The French page takes the date the edition
    keeps; the English page takes the translator's own."""
    import json

    from biread.render import BOOK_DATA_RE

    days = ["MARDI.", "MERCREDI.", "JEUDI.", "VENDREDI."]
    english = ["Tuesday:", "Wednesday:", "Thursday:", "Friday:"]
    french = [Chapter(None, day, [f"Entrée {n}.", f"Encore {n}."])
              for n, day in enumerate(days)]
    published = [Chapter(None, day, [f"Entry {n}.", f"More {n}."])
                 for n, day in enumerate(english)]

    result = build_aligned(title="La Nausée", chapters=french,
                           published_chapters=published, embed=by_section)
    data = json.loads(BOOK_DATA_RE.search(result.html).group(2))

    assert [c["frTitle"] for c in data["chapters"]] == days
    assert [c["enTitle"] for c in data["chapters"]] == english
    assert [c["frEyebrow"] for c in data["chapters"]] == [""] * 4


def test_an_aligned_book_builds_without_a_gloss_client(book, published):
    # Asking for glosses with nothing to make them is not worth refusing a book
    # over: the reader gets the same spread, minus the hover.
    result = build_aligned(
        title="Micromégas", chapters=book, published_chapters=published,
        embed=one_vector, gloss=True,
    )
    assert result.gloss is None
    assert result.alignment.total
    assert "Micromégas" in result.html
