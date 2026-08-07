"""What a file says about itself. Fixtures are built in-code, as elsewhere, so
there are no binaries in the tree."""
import zipfile
from pathlib import Path

from biread.cleanup import Chapter
from biread.meta import describe, looks_scanned

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


def make_pdf(path: Path, **info) -> None:
    """A one-page PDF carrying whatever document information the test needs."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({f"/{k}": v for k, v in info.items()})
    with path.open("wb") as handle:
        writer.write(handle)


def test_pdf_metadata_is_read_from_the_document_information(tmp_path):
    # The same principle as the EPUB's OPF in the other format's vocabulary, and
    # it was simply not being read: the reader was headed with the word "book".
    path = tmp_path / "book.pdf"
    make_pdf(path, Title="La Nausée", Author="Jean-Paul Sartre")
    info = describe(path)
    assert (info.title, info.author) == ("La Nausée", "Jean-Paul Sartre")


def test_a_title_that_is_a_filename_is_the_converter_talking(tmp_path):
    """"Jean-Paul Sartre - Nausea.rtf" is the document Acrobat was pointed at. A
    filename is not a title any more than it is an author."""
    path = tmp_path / "book.pdf"
    make_pdf(path, Title="Jean-Paul Sartre - Nausea.rtf", Author="Kenneth")
    info = describe(path)
    assert info.title is None
    assert info.author == "Kenneth"


def test_a_pdf_that_says_nothing_about_itself_claims_nothing(tmp_path):
    path = tmp_path / "book.pdf"
    make_pdf(path, Title="   ")
    info = describe(path)
    assert (info.title, info.author) == (None, None)
    assert info.pages == 1


def test_a_file_carrying_pictures_of_its_pages_is_a_scan(tmp_path):
    """A scan stores an image of every page beside the characters OCR read off
    it, which is one thing about a file that cannot be faked. Every digitally
    typeset PDF in the corpus sits between 1.1 and 4.1 bytes per character of
    text; the Internet Archive scan of the 1949 Nausea sits at 80.6."""
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"\x00" * 200_000)
    assert looks_scanned(path, "a page of text" * 100)


def test_a_file_that_is_only_its_text_is_not_a_scan(tmp_path):
    path = tmp_path / "book.pdf"
    text = "a page of text" * 1_000
    path.write_bytes(text.encode() * 3)
    assert not looks_scanned(path, text)


def test_an_empty_file_is_not_called_a_scan(tmp_path):
    # Nothing to divide by, and "we could not read this" is a different message.
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"\x00" * 5_000)
    assert not looks_scanned(path, "")
