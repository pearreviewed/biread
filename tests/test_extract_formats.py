"""Extractors for the formats the builder accepts: each yields raw text that
cleanup.py then structures. Fixtures are built in-code so there are no binaries
in the tree."""
import zipfile
from pathlib import Path

import pytest

from biread.errors import ExtractError
from biread.extract import (
    DocxExtractor,
    EpubExtractor,
    HtmlExtractor,
    PdfExtractor,
    TxtExtractor,
    get_extractor,
)


def make_pdf(text: str) -> bytes:
    """A minimal one-page PDF showing `text`, with a correct xref table."""
    stream = b"BT /F1 24 Tf 72 700 Td (" + text.encode("latin-1") + b") Tj ET"
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(len(pdf))
        pdf += str(i).encode() + b" 0 obj" + obj + b"endobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        pdf += ("%010d 00000 n \n" % off).encode()
    pdf += b"trailer<</Size " + str(len(objs) + 1).encode() + b"/Root 1 0 R>>\n"
    pdf += b"startxref\n" + str(xref).encode() + b"\n%%EOF"
    return pdf


def make_docx(path: Path, paragraphs: list[str]) -> None:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    doc = f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", doc)


def make_epub(path: Path, chapters: list[str]) -> None:
    container = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
        '<rootfile full-path="content.opf" media-type="application/oebps-package+xml"/>'
        "</rootfiles></container>"
    )
    items = "".join(
        f'<item id="c{i}" href="ch{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(len(chapters))
    )
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
        f'version="3.0"><manifest>{items}</manifest><spine>{spine}</spine></package>'
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("content.opf", opf)
        for i, text in enumerate(chapters):
            zf.writestr(f"ch{i}.xhtml", f"<html><body><p>{text}</p></body></html>")


def test_html(tmp_path):
    p = tmp_path / "book.html"
    p.write_text(
        "<html><head><style>.x{color:red}</style></head><body>"
        "<h1>Titre</h1><p>Premier paragraphe.</p><p>Second paragraphe.</p></body></html>",
        encoding="utf-8",
    )
    text = HtmlExtractor().extract(p)
    assert "Titre" in text
    assert "Premier paragraphe.\n\nSecond paragraphe." in text
    assert "color:red" not in text  # <style> content dropped


def test_docx(tmp_path):
    p = tmp_path / "book.docx"
    make_docx(p, ["First paragraph.", "Second paragraph."])
    assert DocxExtractor().extract(p) == "First paragraph.\n\nSecond paragraph."


def test_epub_reads_spine_in_order(tmp_path):
    p = tmp_path / "book.epub"
    make_epub(p, ["Chapter one.", "Chapter two."])
    text = EpubExtractor().extract(p)
    assert text.index("Chapter one.") < text.index("Chapter two.")


def test_pdf(tmp_path):
    p = tmp_path / "book.pdf"
    p.write_bytes(make_pdf("Bonjour le monde"))
    assert "Bonjour le monde" in PdfExtractor().extract(p)


def test_pdf_reports_pages_as_it_reads(tmp_path):
    """A slow PDF read is otherwise silent; the callback is what lets the builder
    show 'page 12 of 147'."""
    p = tmp_path / "book.pdf"
    p.write_bytes(make_pdf("Une page"))
    seen = []
    PdfExtractor().extract(p, on_page=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 1)]


def test_a_pageless_format_ignores_the_page_callback(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("Just text.", encoding="utf-8")
    never = lambda *a: (_ for _ in ()).throw(AssertionError("txt has no pages"))
    assert TxtExtractor().extract(p, on_page=never) == "Just text."


def test_pdf_without_text_is_a_clear_error(tmp_path):
    p = tmp_path / "scan.pdf"
    p.write_bytes(make_pdf(" "))
    with pytest.raises(ExtractError, match="selectable|scanned"):
        PdfExtractor().extract(p)


@pytest.mark.parametrize(
    "name,cls",
    [
        ("a.txt", TxtExtractor),
        ("a.html", HtmlExtractor),
        ("a.htm", HtmlExtractor),
        ("a.epub", EpubExtractor),
        ("a.docx", DocxExtractor),
        ("a.pdf", PdfExtractor),
    ],
)
def test_dispatch_by_suffix(name, cls):
    assert isinstance(get_extractor(Path(name)), cls)


def test_dispatch_unknown_format():
    with pytest.raises(ExtractError, match="no extractor"):
        get_extractor(Path("book.mobi"))
