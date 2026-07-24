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

CANDIDE = Path(__file__).resolve().parent.parent / "examples" / "candide-published.pdf"
pytestmark = pytest.mark.skipif(not CANDIDE.exists(), reason="Candide corpus PDF not present")


@pytest.fixture(scope="module")
def candide_chapters():
    raw = PdfExtractor().extract(CANDIDE)
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
