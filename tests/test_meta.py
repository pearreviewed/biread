"""What a file says about itself. Fixtures are built in-code, as elsewhere, so
there are no binaries in the tree."""
import zipfile
from pathlib import Path

from biread.cleanup import Chapter
from biread.meta import describe

CONTAINER = (
    '<?xml version="1.0"?><container version="1.0" '
    'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
    '<rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
    "</rootfiles></container>"
)


def make_epub(path: Path, metadata: str) -> None:
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0">'
        f"<metadata>{metadata}</metadata>"
        '<manifest><item id="c0" href="ch0.xhtml" media-type="application/xhtml+xml"/></manifest>'
        '<spine><itemref idref="c0"/></spine></package>'
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", CONTAINER)
        zf.writestr("content.opf", opf)
        zf.writestr("ch0.xhtml", "<html><body><p>Le chat dort.</p></body></html>")


def epub(tmp_path, metadata):
    path = tmp_path / "book.epub"
    make_epub(path, metadata)
    return path


def test_epub_metadata_is_read_from_the_opf(tmp_path):
    info = describe(epub(tmp_path, (
        "<dc:title>Micromégas</dc:title>"
        "<dc:creator>Voltaire</dc:creator>"
        "<dc:language>fr</dc:language>"
    )))
    assert info.title == "Micromégas"
    assert info.author == "Voltaire"
    assert info.language == "fr"


def test_epub_metadata_is_trimmed(tmp_path):
    info = describe(epub(tmp_path, "<dc:title>\n  Candide\n</dc:title>"))
    assert info.title == "Candide"


def test_a_field_the_epub_omits_stays_none(tmp_path):
    info = describe(epub(tmp_path, "<dc:title>Candide</dc:title><dc:creator></dc:creator>"))
    assert info.title == "Candide"
    assert info.author is None
    assert info.language is None


def test_an_unreadable_epub_says_it_knows_nothing(tmp_path):
    path = tmp_path / "book.epub"
    path.write_bytes(b"not a zip at all")
    info = describe(path)
    assert (info.title, info.author, info.language) == (None, None, None)


def test_a_text_file_knows_nothing_about_itself(tmp_path):
    path = tmp_path / "book.txt"
    path.write_text("Le chat dort.", encoding="utf-8")
    info = describe(path)
    assert (info.title, info.author, info.language, info.pages, info.paragraphs) == (
        None, None, None, None, None,
    )


def test_an_author_is_never_inferred_from_the_filename(tmp_path):
    path = tmp_path / "Voltaire - Candide.txt"
    path.write_text("Le chat dort.", encoding="utf-8")
    assert describe(path).author is None
    assert describe(path).title is None


def test_paragraphs_are_counted_when_the_book_is_given(tmp_path):
    path = tmp_path / "book.txt"
    path.write_text("Le chat dort.", encoding="utf-8")
    chapters = [Chapter("I", "Titre", ["Un.", "Deux."]), Chapter("II", None, ["Trois."])]
    assert describe(path, chapters).paragraphs == 3


def test_an_unreadable_pdf_reports_no_pages(tmp_path):
    path = tmp_path / "book.pdf"
    path.write_bytes(b"not really a PDF")
    assert describe(path).pages is None
