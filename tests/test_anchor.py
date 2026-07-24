"""The anchoring pass: what lets two editions of a book meet without a model.

The cases here are the ones real editions produce — a preface on one side only,
a translator who merges or splits paragraphs, an abridgement, and two books that
simply are not the same book.
"""
from collections import Counter

from biread.align import _distribute
from biread.anchor import MAX_MERGE, agreements, align_by_anchors, fold, longest_run

FRENCH = [
    "Il y avait en Westphalie un jeune garcon nomme Candide.",
    "Pangloss enseignait la metaphysico-theologo-cosmolonigologie.",
    "La fille du baron, Cunegonde, etait fort appetissante.",
    "On le chassa du chateau a grands coups de pied.",
    "Il arriva transi a Waldberghoff-trarbk-dikdorff.",
    "Le tremblement de terre de Lisbonne detruisit la ville en 1755.",
    "Jacques l'anabaptiste perit dans la rade.",
    "L'Inquisition resolut de donner un bel auto-da-fe.",
    "La vieille le conduisit dans une maison ecartee.",
    "Ils voguerent vers Buenos-Ayres chez Don Fernando.",
    "Le jardin de Constantinople fut enfin cultive.",
]

ENGLISH = [
    "There lived in Westphalia a young lad named Candide.",
    "Pangloss taught metaphysico-theologo-cosmolonigology.",
    "The Baron's daughter, Cunegonde, was most appetising.",
    "He was driven from the castle with great kicks.",
    "He arrived frozen at Waldberghoff-trarbk-dikdorff.",
    "The earthquake at Lisbon destroyed the city in 1755.",
    "James the anabaptist perished in the roadstead.",
    "The Inquisition resolved to give a fine auto-da-fe.",
    "The old woman led him to a lonely house.",
    "They sailed for Buenos-Ayres to Don Fernando.",
    "The garden at Constantinople was at last cultivated.",
]

MATTER = [
    "This ebook is for the use of anyone anywhere at no cost.",
    "INTRODUCTION BY THE EDITOR",
    "Voltaire wrote the tale in three days and its gaiety has never left it.",
    "Critics dispute whether the book is a novel at all.",
]

OTHER_BOOK = [
    "Alice was beginning to get very tired of sitting by her sister.",
    "The rabbit-hole went straight on like a tunnel for some way.",
    "Down, down, down. Would the fall never come to an end?",
    "There was a table all made of glass in the long hall.",
    "The Duchess tucked her arm affectionately into Alice's.",
    "The Queen of Hearts she made some tarts all on a summer day.",
    "The Mock Turtle sighed deeply and drew the back of one flapper.",
    "The Gryphon never learnt it, said the Mock Turtle sadly.",
    "Alice thought the whole thing was very absurd indeed.",
    "The jury all wrote down on their slates, important, unimportant.",
    "Off with her head, the Queen shouted at the top of her voice.",
]


def align(right):
    return align_by_anchors(FRENCH, right, _distribute)


def test_a_name_is_recognised_through_its_translated_spelling():
    assert fold("Westphalie") == fold("Westphalia")
    assert fold("Cunégonde") == fold("cunegonde")
    assert fold("Pangloss") != fold("Candide")


def test_a_word_used_all_over_the_book_is_not_evidence():
    """A name in every paragraph cannot say which paragraph is which."""
    assert agreements(["Candide marchait toujours."] * 6, ["Candide always walked."] * 6) == []


def test_a_rare_name_pins_the_paragraph_carrying_it():
    left = ["Rien du tout.", "Cunegonde parut soudain.", "Rien encore."]
    right = ["Nothing at all.", "Cunegonde appeared suddenly.", "Nothing again."]
    assert (1, 1) in agreements(left, right)


def test_a_stray_agreement_is_dropped_from_the_run():
    """A name recurring in an appendix must not drag the book after it."""
    assert longest_run([(0, 0), (1, 1), (2, 9), (3, 2), (4, 3)]) == [(0, 0), (1, 1), (3, 2), (4, 3)]


def test_two_paragraphs_may_anchor_to_one_merged_paragraph():
    """Demanding a strictly increasing run would drop one half of a merge and
    shift every paragraph after it."""
    assert longest_run([(0, 0), (1, 0), (2, 1)]) == [(0, 0), (1, 0), (2, 1)]


def test_a_translation_aligns_paragraph_for_paragraph():
    assert align(ENGLISH) == ENGLISH


def test_front_matter_on_one_side_only_is_left_behind():
    aligned = align(MATTER + ENGLISH)
    assert aligned == ENGLISH
    assert not any("Voltaire" in text or "ebook" in text for text in aligned)


def test_a_merged_translation_shows_the_merge_against_both_paragraphs():
    merged = [ENGLISH[0] + " " + ENGLISH[1]] + ENGLISH[2:]
    aligned = align(merged)
    assert aligned[0] == aligned[1] == merged[0]
    assert aligned[2:] == ENGLISH[2:]


def test_a_split_translation_is_shown_rejoined():
    """A translator who breaks one paragraph in two at a clause boundary: the
    reader should still see the whole of it, in order, beside the French."""
    head, tail = "There lived in Westphalia,", "where a young lad named Candide grew up."
    assert align([head, tail] + ENGLISH[1:])[0] == f"{head} {tail}"


def test_material_an_edition_lacks_is_left_blank_rather_than_repeated():
    """An abridgement drops five paragraphs. Repeating one sentence down the
    page in their place would only look broken."""
    aligned = align(ENGLISH[:3] + ENGLISH[8:])
    assert aligned[:3] == ENGLISH[:3]
    assert "" in aligned
    assert max(Counter(t for t in aligned if t).values()) <= MAX_MERGE


def test_two_different_books_are_refused_rather_than_forced():
    assert align(OTHER_BOOK) is None


def test_too_little_agreement_is_refused():
    """Three paragraphs share a name by chance; that is not a book aligned."""
    assert align_by_anchors(FRENCH[:3], ENGLISH[:3], _distribute) is None


def test_chapter_numbers_can_be_handed_in_as_extra_anchors():
    """Two editions sharing no vocabulary still align if both number chapters."""
    left = ["Le debut.", "La suite.", "Le milieu.", "La fin approche.", "La fin."]
    right = ["Beginning.", "Next.", "Middle.", "Nearly done.", "Done."]
    assert align_by_anchors(left, right, _distribute) is None
    assert align_by_anchors(
        left, right, _distribute, extra=[(0, 0), (1, 1), (2, 2), (4, 4)]
    ) == right
