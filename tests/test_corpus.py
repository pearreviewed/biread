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
    chapters, removed = clean(raw)
    return chapters, removed


@pytest.fixture(scope="module")
def candide_french():
    raw = PdfExtractor().extract(CANDIDE_FR)
    chapters, removed = clean(raw)
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
