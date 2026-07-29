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
