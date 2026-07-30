"""End-to-end extraction → cleanup on real, awkward books.

The unit tests prove each repair in isolation on a tiny fixture; these prove the
pipeline survives a genuine source with all its damage at once. Candide is the
first corpus member: a Project Gutenberg PDF whose thirty chapters are marked by
a lone roman numeral, stamped through with page markers, and wrapped in a table
of contents and a licence. It used to collapse into one 183-paragraph blob.
"""
from pathlib import Path

import pytest

from biread.cleanup import clean

pytest.importorskip("pypdf")
from biread.extract.pdf import PdfExtractor  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CANDIDE = EXAMPLES / "candide-published.pdf"
CANDIDE_FR = EXAMPLES / "candide-french.pdf"
pytestmark = pytest.mark.skipif(not CANDIDE.exists(), reason="Candide corpus PDF not present")


@pytest.fixture(scope="module")
def candide_chapters():
    raw = PdfExtractor().extract(CANDIDE)
    chapters, removed = clean(raw, from_pdf=True)
    return chapters, removed


@pytest.fixture(scope="module")
def candide_french():
    raw = PdfExtractor().extract(CANDIDE_FR)
    chapters, removed = clean(raw, from_pdf=True)
    return chapters, removed


def test_all_thirty_chapters_are_found(candide_chapters):
    chapters, _ = candide_chapters
    numbered = [c for c in chapters if c.number]
    assert len(numbered) == 30
    from biread.numbering import chapter_number
    assert [chapter_number(c.number) for c in numbered] == list(range(1, 31))


def test_chapter_titles_survive(candide_chapters):
    chapters, _ = candide_chapters
    first = next(c for c in chapters if c.number == "I")
    assert first.title and "CANDIDE" in first.title.upper()


def test_page_markers_were_stripped_from_the_body(candide_chapters):
    chapters, removed = candide_chapters
    body = " ".join(p for c in chapters for p in c.paragraphs)
    assert "[Pg" not in body
    assert any(r.kind == "Page marker" for r in removed)


def test_the_book_did_not_collapse_into_one_blob(candide_chapters):
    chapters, _ = candide_chapters
    assert len(chapters) > 20


# The French edition numbers its chapters in words, and past sixteen those words
# are hyphenated compounds — "dix-septième", "vingt-neuvième". The heading pattern
# used to sever them at the hyphen, so it found only chapters 1–16 and 20, lost
# twelve headings into the body, and (because the last number it could read was
# twenty) trimmed chapters 21–30 off the book entirely.
@pytest.mark.skipif(not CANDIDE_FR.exists(), reason="French Candide corpus PDF not present")
class TestFrenchCandide:
    def test_all_thirty_chapters_are_found(self, candide_french):
        from biread.numbering import chapter_number

        chapters, _ = candide_french
        numbers = [chapter_number(c.number) for c in chapters if c.number]
        assert numbers == list(range(1, 31))

    def test_each_chapter_argument_becomes_a_title(self, candide_french):
        # The descriptive line under each chapter number is its title, not a body
        # paragraph facing the other edition's prose.
        chapters, _ = candide_french
        numbered = [c for c in chapters if c.number]
        assert all(c.title for c in numbered)
        assert numbered[0].title.startswith("Comment Candide")

    def test_the_whole_book_survives_trimming(self, candide_french):
        # Trimming used to stop at chapter twenty and drop the last third of the
        # book; every chapter one through thirty must reach the reader.
        from biread.align import trim_matter
        from biread.numbering import chapter_number

        chapters, _ = candide_french
        body = trim_matter(chapters)
        assert [chapter_number(c.number) for c in body if c.number] == list(range(1, 31))

    def test_the_trailing_bibliography_is_dropped(self, candide_french):
        # This edition appends a hundred-odd bibliography entries after the
        # conclusion; they are apparatus, not the book, and must not be aligned.
        from biread.align import trim_matter

        chapters, _ = candide_french
        text = " ".join(p for c in trim_matter(chapters) for p in c.paragraphs)
        assert "BIBLIOGRAPHIE" not in text
        assert "Zadoukal" not in text  # a bibliography author, well past the conclusion

    def test_the_two_editions_align_full_and_balanced(self, candide_french, candide_chapters):
        # The free path against the published English: every French paragraph must
        # find a counterpart (no blank facing a wall of text), and no run of
        # English may be smeared across a long stretch of French.
        from collections import Counter

        from biread.align import align_published

        french, _ = candide_french
        english, _ = candide_chapters
        aligned, report = align_published(french, english, None)
        assert report.coverage == 1.0 and not report.degraded
        assert "" not in aligned.values()
        repeats = Counter(t for t in aligned.values() if t)
        assert max(repeats.values()) <= 3


# ---- paragraphs, which is where the damage moved once chapters were found ----

def test_the_published_edition_comes_apart_into_paragraphs(candide_chapters):
    """It used to arrive as 120 lumps, one of them four pages long, because this
    PDF does not put a blank line between every paragraph."""
    chapters, _ = candide_chapters
    paragraphs = [p for c in chapters for p in c.paragraphs]
    assert len(paragraphs) > 600
    # Four pages of prose is not a paragraph; it is several with the seams lost.
    assert max(len(p) for p in paragraphs) < 4000


def test_the_two_editions_are_of_comparable_scale(candide_chapters, candide_french):
    """Alignment matches paragraph to paragraph, so one side arriving in lumps
    five times the size of the other is fatal however good the matcher is."""
    published = [p for c in candide_chapters[0] for p in c.paragraphs]
    french = [p for c in candide_french[0] for p in c.paragraphs]
    assert 0.5 < len(french) / len(published) < 2.0


def test_both_editions_open_on_the_same_first_line(candide_chapters, candide_french):
    from biread.align import trim_matter

    def opening(chapters):
        body = [c for c in trim_matter(chapters) if c.paragraphs] or chapters
        return body[0].paragraphs[0]

    # Not the licence, not the transcriber's note, not the title page.
    assert "Vestphalie" in opening(candide_french[0])
    assert "Westphalia" in opening(candide_chapters[0])


def test_the_repair_is_reported_not_silent(candide_chapters):
    _, removed = candide_chapters
    assert any(r.kind == "Paragraph break restored" for r in removed)


# ---- a book in parts, from an EPUB (Madame Bovary) ----

BOVARY_FR = EXAMPLES / "bovary-french.epub"
BOVARY_EN = EXAMPLES / "bovary-published.epub"
bovary = pytest.mark.skipif(not BOVARY_FR.exists(), reason="Bovary corpus EPUBs not present")


@pytest.fixture(scope="module")
def bovary_editions():
    from biread.align import trim_matter
    from biread.extract import get_extractor

    def load(path):
        chapters, _ = clean(get_extractor(path).extract(path))
        return [c for c in trim_matter(chapters) if c.paragraphs] or chapters

    return load(BOVARY_FR), load(BOVARY_EN)


@bovary
def test_both_editions_find_all_thirty_five_chapters(bovary_editions):
    """Three parts numbered I..IX, I..XV, I..XI. Read as one ascending spine the
    novel collapsed into a single chapter, its 3,087 paragraphs under the last
    line of the table of contents."""
    for chapters in bovary_editions:
        assert len(chapters) == 35


@bovary
def test_both_editions_agree_on_the_three_parts(bovary_editions):
    for chapters in bovary_editions:
        assert [c.part for c in chapters] == [1] * 9 + [2] * 15 + [3] * 11


@bovary
def test_the_two_editions_pair_chapter_for_chapter(bovary_editions):
    """The French numbers its chapters in roman and the English spells them out
    ("One", "Nine"); neither is worth anything unless the part is carried too,
    since each edition has three chapter ones."""
    from biread.align import _chapter_pairs

    french, published = bovary_editions
    pairs = _chapter_pairs(french, published)
    assert len(pairs) == 35
    assert all(pub is not None for _, pub in pairs)


@bovary
def test_the_novel_opens_on_its_first_line_in_both(bovary_editions):
    french, published = bovary_editions
    assert french[0].paragraphs[0].startswith("Nous étions à l")
    assert published[0].paragraphs[0].startswith("We were in class")
