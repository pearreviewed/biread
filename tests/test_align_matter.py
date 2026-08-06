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

# Long enough to be a book rather than a sample of one: an introduction is a
# minority of any real file, and trimming now refuses to drop a leading section
# that outweighs the text — so a two-sentence book would test the wrong thing.
FRENCH = """CHAPITRE premier

Comment Candide fut eleve.

Il y avait en Westphalie un jeune garcon a qui la nature avait donne les moeurs les plus douces.

Le baron etait un des plus puissants seigneurs de la province, car son chateau avait une porte et des fenetres.

Pangloss enseignait la metaphysico-theologo-cosmolonigologie, et prouvait que tout est au mieux.

Il prouvait admirablement qu'il n'y a point d'effet sans cause, et que tout est fait pour une fin.

Cunegonde, agee de dix-sept ans, etait haute en couleur, fraiche, grasse et fort appetissante.

Un jour Cunegonde rencontra Candide en revenant au chateau, et tous deux rougirent beaucoup.

CHAPITRE second

Ce que devint Candide.

Candide chasse du paradis terrestre marcha longtemps sans savoir ou aller.

Il se coucha sans souper au milieu des champs, et la neige tombait a gros flocons.

Deux hommes habilles de bleu le remarquerent et le prierent a diner fort civilement.

Candide leur dit avec une modestie charmante qu'il leur faisait beaucoup d'honneur.

On le mena dans un cachot, et on lui demanda s'il aimait mieux etre fustige ou fusille.

Il choisit, en vertu du don de Dieu qu'on nomme liberte, de passer par les baguettes.
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

The baron was one of the most powerful lords of the province, for his castle had a door and windows.

Pangloss taught metaphysico-theologo-cosmolonigology, and proved that all is for the best.

He proved admirably that there is no effect without a cause, and that all is made to an end.

Cunegonde, aged seventeen, was of a high colour, fresh, plump, and very appetising indeed.

One day Cunegonde met Candide on her way back to the castle, and they both blushed a great deal.

CHAPTER II

What became of Candide.

Candide, driven out of the earthly paradise, walked a long while without knowing where.

He lay down supperless in the middle of the fields, and the snow fell in great flakes.

Two men dressed in blue noticed him and invited him to dinner most civilly.

Candide told them with a charming modesty that they did him a great deal of honour.

He was led into a dungeon, and asked whether he would rather be flogged or shot.

He chose, in virtue of the gift of God called liberty, to run the gauntlet.
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


def test_a_leading_section_larger_than_the_book_is_not_front_matter():
    # The safety net under chapter detection: where a false heading is found part
    # way into a book, trimming to it would delete everything before it in
    # silence. A title page and an introduction are small beside the book, so a
    # "front matter" outweighing the text is a heading that was never a chapter's.
    opening = [f"The book opens, and goes on for a while: paragraph {i}." for i in range(20)]
    chapters = [
        Chapter(None, None, opening),
        Chapter("1", None, ["A short section that follows it."]),
        Chapter("2", None, ["And a second short section."]),
    ]
    assert [c.number for c in trim_matter(chapters)] == [None, "1", "2"]


def test_trim_drops_a_trailing_bibliography():
    # An academic edition appends a bibliography after the last chapter; it has no
    # counterpart in the other edition and must not be set beside it.
    chapters = [
        Chapter("I", None, ["The story begins in a quiet town."]),
        Chapter("II", None, [
            "And the story comes to its end.",
            "BIBLIOGRAPHIE",
            "Author, A., 'A study of the book', Journal (1990), i.1-20.",
            "Author, B., 'Another study entirely', Review (1991), ii.3-9.",
        ]),
    ]
    body = [p for c in trim_matter(chapters) for p in c.paragraphs]
    assert body == ["The story begins in a quiet town.", "And the story comes to its end."]


def test_a_mid_book_mention_of_notes_is_not_mistaken_for_back_matter():
    # Only a paragraph that is the apparatus heading and nothing else is a cut
    # point, and only in the back half — a sentence mentioning notes is safe.
    chapters = [
        Chapter("I", None, ["He took careful notes on the lecture that morning."]),
        Chapter("II", None, ["The index of his suspicions grew by the day.", "The end."]),
    ]
    body = [p for c in trim_matter(chapters) for p in c.paragraphs]
    assert len(body) == 3


def test_a_book_with_no_numbered_chapters_is_left_alone():
    chapters = [Chapter(None, None, ["Just prose, with no headings at all."])]
    assert trim_matter(chapters) == chapters


def test_a_one_sided_introduction_does_not_shift_the_book():
    """The failure this was written for: one edition's introduction used to push
    every paragraph out of step, so chapter one met a critical essay."""
    french, _ = clean(FRENCH)
    english, _ = clean(ENGLISH)
    aligned, report = align_published(french, english, None)

    assert "Westphalia" in aligned[hash_text(french[0].paragraphs[0])]
    assert "earthly paradise" in aligned[hash_text(french[1].paragraphs[0])]
    assert report.chapters_matched
    assert not any("essay" in text or "Produced by" in text for text in aligned.values())


def test_chapters_pair_by_number_not_by_position():
    """`premier` and `I` are the same chapter however differently they are spelled."""
    french, _ = clean(FRENCH)
    english, _ = clean(ENGLISH)
    aligned, _ = align_published(french, english, None)
    first = french[0].paragraphs[0]
    assert "Westphalia" in aligned[hash_text(first)]


def test_chapter_arguments_are_paired_as_titles():
    """Each chapter's descriptive argument is set beside its counterpart, so both
    editions open the chapter on the same line rather than a heading facing prose."""
    french = [
        Chapter("premier", "Comment Candide fut eleve.", ["Il y avait en Westphalie un garcon nomme Candide."]),
        Chapter("second", "Ce que devint Candide.", ["Candide chasse marcha longtemps sans savoir ou aller."]),
    ]
    english = [
        Chapter("I", "HOW CANDIDE WAS BROUGHT UP.", ["There lived in Westphalia a lad named Candide."]),
        Chapter("II", "WHAT BECAME OF CANDIDE.", ["Candide, driven out, walked a long while."]),
    ]
    aligned, _ = align_published(french, english, None)
    assert aligned[hash_text("Comment Candide fut eleve.")] == "HOW CANDIDE WAS BROUGHT UP."
    assert aligned[hash_text("Ce que devint Candide.")] == "WHAT BECAME OF CANDIDE."


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


def test_the_refusal_names_the_file_and_the_format_that_lost_the_breaks():
    # Two files are in play on the align route and only one of them is at fault;
    # naming it, and the file it was converted from, is the whole of what a
    # reader needs. Blaming PDFs for a Word file's damage is what it used to do.
    blob = [Chapter("1", None, ["word " * 4000])]
    with pytest.raises(ExtractError) as e:
        check_usable(blob, "The book", "book.docx")
    assert "book.docx did not come apart" in str(e.value)
    assert "Word file converted from a PDF" in str(e.value)
    assert "PDF or EPUB it was made from" in str(e.value)


def test_a_pdf_is_pointed_somewhere_a_word_file_is_not():
    blob = [Chapter("1", None, ["word " * 4000])]
    with pytest.raises(ExtractError, match="EPUB or plain-text edition"):
        check_usable(blob, "The book", "candide.pdf")


def test_ordinary_prose_is_accepted():
    check_usable([Chapter("1", None, ["A paragraph of ordinary length. " * 10])], "The book")


def test_no_chapter_book_opens_on_real_text_not_the_title_page():
    chapters = [Chapter(None, None, [
        "Produced by Some Volunteer and the Online Distributed Proofreading Team.",
        "Transcriber's Note: obvious errors have been corrected.",
        "THE MODERN LIBRARY",
        "CANDIDE BY VOLTAIRE",
        "In a castle of Westphalia there lived a young man of the gentlest manners.",
        "He was called Candide by the old servants of the house.",
    ])]
    trimmed = trim_matter(chapters)
    assert trimmed[0].paragraphs[0].startswith("In a castle of Westphalia")
    assert not any("Produced by" in p or "MODERN LIBRARY" in p
                   for c in trimmed for p in c.paragraphs)


def test_a_named_introduction_is_kept_as_the_opening():
    chapters = [Chapter(None, None, [
        "Produced by a Project Gutenberg volunteer.",
        "Introduction",
        "This preface is part of the work and the reader should see it.",
        "The story itself begins a little further on.",
    ])]
    trimmed = trim_matter(chapters)
    assert trimmed[0].paragraphs[0] == "Introduction"


def test_a_real_opening_line_is_never_mistaken_for_matter():
    chapters = [Chapter(None, None, ["It was a bright cold day in April."])]
    assert trim_matter(chapters) == chapters


def test_length_matching_places_a_long_stretch_with_a_long_paragraph():
    # A short French paragraph and a long one; the published side splits the long
    # one into many pieces. Length-matching must keep the short one short.
    french = [Chapter("I", None, [
        "Bref.",
        "Un paragraphe beaucoup plus long qui continue et continue sans fin apparente.",
    ])]
    published = [Chapter("I", None, [
        "Short.",
        "A much ", "longer paragraph ", "that goes on ", "and on and on ", "without any end.",
    ])]
    aligned, _ = align_published(french, published, None)
    assert aligned[hash_text("Bref.")] == "Short."
    long_side = aligned[hash_text(french[0].paragraphs[1])]
    assert long_side.startswith("A much") and long_side.endswith("without any end.")


def test_coverage_is_reported_and_high_when_editions_line_up():
    french, _ = clean(FRENCH)
    english, _ = clean(ENGLISH)
    _, report = align_published(french, english, None)
    assert report.total == 12
    assert report.coverage == 1.0
    assert not report.degraded


def test_coverage_and_degraded_are_computed_from_the_blanks():
    from biread.align import AlignmentReport
    report = AlignmentReport(method="anchored", chapters_matched=True, total=10, unmatched=8)
    assert report.coverage == 0.2
    assert report.degraded
    assert not AlignmentReport(method="anchored", chapters_matched=True,
                               total=10, unmatched=1).degraded


def test_an_abridged_edition_missing_most_chapters_is_flagged_degraded():
    # Five French chapters, a published edition carrying only the first two: the
    # other three are left blank, so most of the column is missing.
    french = [Chapter(n, None, [f"Paragraphe {n}-{i}." for i in range(2)])
              for n in ["I", "II", "III", "IV", "V"]]
    english = [Chapter("I", None, ["Chapter one, first.", "Chapter one, second."]),
               Chapter("II", None, ["Chapter two, first.", "Chapter two, second."])]
    _, report = align_published(french, english, None)
    assert report.total == 10
    assert report.coverage < 0.7 and report.degraded


def test_degraded_note_says_so_plainly_with_a_percentage():
    from biread.align import AlignmentReport
    from biread.build import published_note
    report = AlignmentReport(method="anchored", chapters_matched=True, total=10, unmatched=8)
    note = published_note(report)
    assert "%" in note and "left blank" in note


def test_a_healthy_note_makes_no_coverage_warning():
    from biread.build import published_note
    french, _ = clean(FRENCH)
    english, _ = clean(ENGLISH)
    _, report = align_published(french, english, None)
    assert "left blank" not in published_note(report)
