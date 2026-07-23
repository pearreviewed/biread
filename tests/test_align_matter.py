"""Alignment has to survive what readers actually bring: an edition that opens
with a critic's introduction, another that numbers its chapters in words rather
than numerals, and a PDF whose text never broke into paragraphs at all.
"""
import pytest

from biread.align import align_published, chapter_number, trim_matter
from biread.build import check_usable
from biread.cleanup import Chapter, clean
from biread.errors import ExtractError
from biread.translate import hash_text

FRENCH = """CHAPITRE premier

Comment Candide fut eleve.

Il y avait en Westphalie un jeune garcon a qui la nature avait donne les moeurs les plus douces.

CHAPITRE second

Ce que devint Candide.

Candide chasse du paradis terrestre marcha longtemps sans savoir ou aller.
"""

# The same book — but this edition opens with a publisher's notice and a long
# critical introduction, and numbers its chapters in roman rather than in words.
ENGLISH = """Produced by Some Volunteer at Project Gutenberg. This ebook is for anyone anywhere.

INTRODUCTION

Voltaire is a writer whose gaiety survives translation, and this essay runs on for pages before the novel begins.

The essay continues at length, discussing optimism, and is still not the book.

CHAPTER I

How Candide was brought up.

There lived in Westphalia a young lad on whom nature had bestowed the gentlest of manners.

CHAPTER II

What became of Candide.

Candide, driven out of the earthly paradise, walked a long while without knowing where.
"""


@pytest.mark.parametrize(
    "token,number",
    [
        ("I", 1), ("IV", 4), ("4", 4),
        ("premier", 1), ("quatrième", 4), ("fourth", 4), ("second", 2),
        ("dix", 10),      # the French word for ten, not the roman numeral 509
        ("PAGE", None),   # a table-of-contents header, not a chapter
        ("", None), (None, None),
    ],
)
def test_chapter_numbers_normalise_across_styles(token, number):
    assert chapter_number(token) == number


def test_trim_drops_the_matter_that_brackets_a_book():
    chapters, _ = clean(ENGLISH)
    assert chapters[0].number is None  # the notice and the introduction
    assert [c.number for c in trim_matter(chapters)] == ["I", "II"]


def test_a_book_with_no_numbered_chapters_is_left_alone():
    chapters = [Chapter(None, None, ["Just prose, with no headings at all."])]
    assert trim_matter(chapters) == chapters


def test_a_one_sided_introduction_does_not_shift_the_book():
    """The failure this was written for: one edition's introduction used to push
    every paragraph out of step, so chapter one met a critical essay."""
    french, _ = clean(FRENCH)
    english, _ = clean(ENGLISH)
    aligned, report = align_published(french, english, None)

    body = [p for chapter in french for p in chapter.paragraphs]
    assert "Westphalia" in aligned[hash_text(body[0])]
    assert "earthly paradise" in aligned[hash_text(body[1])]
    assert report.chapters_matched
    assert not any("essay" in text or "Produced by" in text for text in aligned.values())


def test_chapters_pair_by_number_not_by_position():
    """`premier` and `I` are the same chapter however differently they are spelled."""
    french, _ = clean(FRENCH)
    english, _ = clean(ENGLISH)
    aligned, _ = align_published(french, english, None)
    first = french[0].paragraphs[0]
    assert "Westphalia" in aligned[hash_text(first)]


def test_a_french_chapter_with_no_counterpart_is_left_blank():
    """An abridged edition is missing a chapter; the rest must not shift up to
    cover the gap, and the gap itself is left empty rather than guessed at."""
    french = [
        Chapter("premier", None, ["Le premier."]),
        Chapter("second", None, ["Le second."]),
        Chapter("troisième", None, ["Le troisieme."]),
    ]
    english = [Chapter("I", None, ["The first."]), Chapter("II", None, ["The second."])]
    aligned, report = align_published(french, english, None)
    assert aligned[hash_text("Le premier.")] == "The first."
    assert aligned[hash_text("Le second.")] == "The second."
    assert aligned[hash_text("Le troisieme.")] == ""
    assert report.unmatched == 1


def test_text_that_never_broke_into_paragraphs_is_refused():
    blob = [Chapter("1", None, ["word " * 4000])]
    with pytest.raises(ExtractError, match="did not come apart into paragraphs"):
        check_usable(blob, "The published translation")


def test_ordinary_prose_is_accepted():
    check_usable([Chapter("1", None, ["A paragraph of ordinary length. " * 10])], "The book")
