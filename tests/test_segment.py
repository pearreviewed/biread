"""Cutting a flattened edition to the shape of the one beside it.

The measurement at the end is the real test. Every arithmetic bug this code had —
breaks placed by pouring rather than absolutely, positions counted without the
joining space, a boundary landing on a sentence counted as inside it — passed
every small example and cost two thirds of a book, and only a whole book showed
it: 3%, then 21%, then 40%, then 80% of the paragraphs coming back whole.
"""
import re
from pathlib import Path

import pytest

from biread.build import cut_note, recut
from biread.align import AlignmentReport
from biread.cleanup import Chapter, clean
from biread.extract import get_extractor
from biread.segment import segment_like, unsegmented

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def flat(text: str) -> list[Chapter]:
    return [Chapter(None, None, [text])]


def chapter(paragraphs, number="I"):
    return Chapter(number, None, list(paragraphs))


# ---- what counts as flat ----

def test_ordinary_paragraphs_are_not_flat():
    assert not unsegmented([chapter(["A paragraph of ordinary length. " * 8] * 5)])


def test_a_book_in_one_block_is_flat():
    assert unsegmented(flat("word " * 4000))


def test_nothing_is_not_flat():
    assert not unsegmented([])
    assert not unsegmented([Chapter(None, None, [])])


# ---- the cut ----

def test_a_blob_takes_the_paragraph_count_of_the_book_beside_it():
    counterpart = chapter(["Le chat dort.", "Le chien court.", "L'oiseau vole."])
    cut = segment_like(flat("The cat sleeps. The dog runs. The bird flies."), [counterpart])
    assert [p for c in cut for p in c.paragraphs] == [
        "The cat sleeps.", "The dog runs.", "The bird flies."
    ]


def test_the_cut_keeps_every_word_and_every_quotation_mark():
    text = 'He said "Yes." Then she left. "Why?" he asked. Nothing at all.'
    counterpart = chapter(["Un.", "Deux.", "Trois.", "Quatre."])
    cut = segment_like(flat(text), [counterpart])
    assert " ".join(p for c in cut for p in c.paragraphs) == text


def test_the_cut_inherits_the_other_edition_s_chapters():
    counterpart = [Chapter("I", "Le début", ["Un. Deux."]),
                   Chapter("II", "La fin", ["Trois. Quatre."])]
    cut = segment_like(flat("One. Two. Three. Four."), counterpart)
    assert [(c.number, c.title) for c in cut] == [("I", "Le début"), ("II", "La fin")]


def test_a_long_paragraph_draws_more_than_a_short_one():
    counterpart = chapter(["x" * 200, "y" * 20])
    cut = segment_like(flat("One. Two. Three. Four. Five. Six."), [counterpart])
    drawn = [p for c in cut for p in c.paragraphs]
    assert len(drawn) == 2 and len(drawn[0]) > len(drawn[1])


def test_nothing_to_cut_against_leaves_the_text_alone():
    blob = flat("word " * 4000)
    assert segment_like(blob, []) == blob
    assert segment_like([], [chapter(["Un."])]) == []


# ---- which side gets cut ----

# Long enough to be flat by the same measure the build uses: `recut` fires on a
# book that arrived in blocks no prose is set in, not on a short fused passage.
FRENCH = [f"Le chat numéro {n} dort sur la table de la cuisine et ne bouge pas. " * 4
          for n in range(40)]
ENGLISH = [f"Cat number {n} sleeps on the kitchen table and does not stir. " * 4
           for n in range(40)]


def test_the_flat_side_is_cut_and_named():
    _, published, which = recut([chapter(FRENCH)], flat(" ".join(ENGLISH)))
    assert which == "published"
    assert len([p for c in published for p in c.paragraphs]) == len(ENGLISH)


def test_a_flat_original_is_cut_to_the_translation():
    original, _, which = recut(flat(" ".join(FRENCH)), [chapter(ENGLISH)])
    assert which == "original"
    assert len([p for c in original for p in c.paragraphs]) == len(FRENCH)


def test_two_flat_editions_are_left_to_be_refused():
    # Neither can supply the other's shape, and inventing one is the thing this
    # deliberately does not do.
    blob = flat("word " * 4000)
    original, published, which = recut(blob, flat("mot " * 4000))
    assert which == "" and original is blob


def test_two_good_editions_are_untouched():
    good, other = [chapter(["Un.", "Deux."])], [chapter(["One.", "Two."])]
    assert recut(good, other) == (good, other, "")


def test_a_book_with_no_second_edition_is_untouched():
    blob = flat("word " * 4000)
    assert recut(blob, None) == (blob, None, "")


# ---- the reader is told ----

@pytest.mark.parametrize("which,said", [
    ("published", "The edition you brought arrived with its paragraph breaks lost"),
    ("original", "The original arrived with its paragraph breaks lost"),
])
def test_a_cut_edition_says_so_on_the_page(which, said):
    assert said in cut_note(AlignmentReport(method="pivot", chapters_matched=True, cut=which))


def test_a_book_that_was_not_cut_says_nothing():
    assert cut_note(AlignmentReport(method="pivot", chapters_matched=True)) == ""


# ---- the measurement ----

def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def whole_paragraphs_recovered(path: Path) -> tuple[int, int, int]:
    """Flatten a real book, cut it back against itself, and count what returns.

    Against itself on purpose: this isolates the cutting from every difference
    two editions have, and it is the one regime where the right answer is known
    exactly. The ceiling is below 100% because a paragraph closing without a full
    stop — a heading, a line of verse — leaves no sentence break to find.
    """
    truth = [c for c in clean(get_extractor(path).extract(path))[0] if c.paragraphs]
    real = [p for c in truth for p in c.paragraphs]
    blob = flat(" ".join(real))

    cut = segment_like(blob, truth)
    want: dict[str, int] = {}
    for paragraph in real:
        want[norm(paragraph)] = want.get(norm(paragraph), 0) + 1
    recovered = 0
    for paragraph in (p for c in cut for p in c.paragraphs):
        if want.get(norm(paragraph)):
            want[norm(paragraph)] -= 1
            recovered += 1
    return recovered, len(real), sum(len(c.paragraphs) for c in cut)


@pytest.mark.parametrize("name,least", [
    ("bovary-published.epub", 0.72),
    ("bovary-french.epub", 0.70),
    ("candide-published.pdf", 0.62),
])
def test_most_of_a_flattened_book_comes_back(name, least):
    path = EXAMPLES / name
    if not path.exists():
        pytest.skip(f"{name} is not in examples/")
    recovered, total, _ = whole_paragraphs_recovered(path)
    assert recovered / total >= least, (
        f"{recovered}/{total} paragraphs came back whole ({recovered / total:.0%}), "
        f"below the {least:.0%} this has held at"
    )


def test_the_cut_book_is_about_as_long_as_the_real_one():
    path = EXAMPLES / "bovary-published.epub"
    if not path.exists():
        pytest.skip("bovary-published.epub is not in examples/")
    _, total, cut = whole_paragraphs_recovered(path)
    assert 0.85 <= cut / total <= 1.05
