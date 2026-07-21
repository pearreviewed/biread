import xml.dom.minidom as minidom
import zipfile

from biread.cleanup import Chapter
from biread.export import write_epub
from biread.gloss import GlossUnit
from biread.translate import hash_text

FR1 = "Il s'appelait Micromégas, nom qui convient."
FR2 = "Les < & > périls de l'escalier."   # deliberately XML-hostile


def book_with_gloss():
    chapters = [Chapter("I", "Le Départ", [FR1, FR2])]
    translations = {hash_text(FR1): "He was called Micromégas.",
                    hash_text(FR2): "The perils of the staircase."}
    units = [GlossUnit(0, 13, "verb", "he was called", "s'appeler", "il s'est appelé")]
    glosses = {hash_text(FR1): units}
    return chapters, translations, glosses


def read_epub(path):
    z = zipfile.ZipFile(path)
    return z, {n: z.read(n).decode("utf-8") for n in z.namelist() if n != "mimetype"}


def test_epub_has_the_required_skeleton(tmp_path):
    chapters, translations, glosses = book_with_gloss()
    out = tmp_path / "b.epub"
    write_epub("Essai", chapters, translations, glosses, out)

    z = zipfile.ZipFile(out)
    names = z.namelist()
    for required in ("mimetype", "META-INF/container.xml", "OEBPS/content.opf", "OEBPS/nav.xhtml"):
        assert required in names, required


def test_the_mimetype_is_first_and_stored(tmp_path):
    # A reader may sniff the mimetype by byte offset, so it must be the first
    # entry and uncompressed.
    chapters, translations, glosses = book_with_gloss()
    out = tmp_path / "b.epub"
    write_epub("Essai", chapters, translations, glosses, out)

    first = zipfile.ZipFile(out).infolist()[0]
    assert first.filename == "mimetype"
    assert first.compress_type == zipfile.ZIP_STORED
    assert zipfile.ZipFile(out).read("mimetype") == b"application/epub+zip"


def test_every_xml_document_is_well_formed(tmp_path):
    # An escaping bug would corrupt the archive; FR2 carries < & > on purpose.
    chapters, translations, glosses = book_with_gloss()
    out = tmp_path / "b.epub"
    write_epub("Essai", chapters, translations, glosses, out)

    z, files = read_epub(out)
    xml_files = [n for n in files if n.endswith((".xhtml", ".opf", ".xml"))]
    assert xml_files
    for name in xml_files:
        minidom.parseString(files[name])  # raises on malformed


def test_french_and_english_interleave(tmp_path):
    chapters, translations, glosses = book_with_gloss()
    out = tmp_path / "b.epub"
    write_epub("Essai", chapters, translations, glosses, out)

    _, files = read_epub(out)
    chapter = files["OEBPS/chapter0.xhtml"]
    assert chapter.index('class="fr"') < chapter.index('class="en"')
    assert "He was called Micromégas." in chapter


def test_a_gloss_becomes_a_footnote_reference(tmp_path):
    chapters, translations, glosses = book_with_gloss()
    out = tmp_path / "b.epub"
    write_epub("Essai", chapters, translations, glosses, out)

    _, files = read_epub(out)
    chapter = files["OEBPS/chapter0.xhtml"]
    assert 'epub:type="noteref"' in chapter
    assert 'epub:type="footnote"' in chapter
    # every reference resolves to exactly one note
    assert chapter.count('epub:type="noteref"') == chapter.count('epub:type="footnote"')
    assert "he was called" in chapter      # the gloss
    assert "inf. s'appeler" in chapter     # the infinitive
    assert "p.c. il s'est appelé" in chapter


def test_a_paragraph_without_glosses_has_no_notes(tmp_path):
    chapters = [Chapter("I", "Sans", ["Une phrase simple."])]
    translations = {hash_text("Une phrase simple."): "A simple sentence."}
    out = tmp_path / "b.epub"
    write_epub("Essai", chapters, translations, {}, out)

    _, files = read_epub(out)
    assert 'epub:type="footnote"' not in files["OEBPS/chapter0.xhtml"]


def test_over_broad_units_are_filtered_from_the_export_too(tmp_path):
    # The export shows what the reader shows: a two-noun unit is not a hover.
    fr = "Les citoyens de la terre."
    chapters = [Chapter("I", None, [fr])]
    wide = [GlossUnit(4, 24, "noun phrase", "citizens of the earth")]  # "citoyens de la terre"
    out = tmp_path / "b.epub"
    write_epub("Essai", chapters, {hash_text(fr): "The citizens of the earth."}, {hash_text(fr): wide}, out)

    _, files = read_epub(out)
    assert 'epub:type="noteref"' not in files["OEBPS/chapter0.xhtml"]


# ---- PDF: the print layout (HTML generation is pure; rendering needs a browser) ----

from biread.export.pdf import _print_html


def test_pdf_puts_french_and_english_in_aligned_columns():
    chapters = [Chapter("I", "Le Départ", [FR1])]
    html = _print_html("Essai", chapters, {hash_text(FR1): "He was called Micromégas."})
    # one table row, French cell then English cell
    assert '<td class="fr"' in html and '<td class="en"' in html
    assert html.index('class="fr"') < html.index('class="en"')
    assert "He was called Micromégas." in html


def test_pdf_carries_no_glosses():
    # PDF drops glosses on purpose; footnotes would crowd a printed page.
    chapters = [Chapter("I", None, [FR1])]
    html = _print_html("Essai", chapters, {hash_text(FR1): "x"})
    assert "noteref" not in html and "footnote" not in html


def test_pdf_escapes_xml_hostile_text():
    chapters = [Chapter("I", None, [FR2])]
    html = _print_html("Essai", chapters, {hash_text(FR2): "a < b & c"})
    assert "&lt;" in html and "&amp;" in html
    assert "< &" not in html.split("<body>")[1]  # no raw hostile chars in the body


def test_pdf_headings_span_both_columns():
    chapters = [Chapter("IV", "Le Titre", ["Une phrase."])]
    html = _print_html("Essai", chapters, {})
    assert 'colspan="2"' in html
    assert "Le Titre" in html and "Chapitre IV" in html


# ---- PDF rendering itself needs Chromium; skipped without the [browser] extra ----

import pytest

try:
    import playwright.sync_api  # noqa: F401
    HAS_BROWSER = True
except ImportError:
    HAS_BROWSER = False


@pytest.mark.skipif(not HAS_BROWSER, reason="PDF export needs the [browser] extra")
def test_write_pdf_produces_a_real_pdf(tmp_path):
    from biread.export import write_pdf
    chapters = [Chapter("I", "Le Départ", ["Une phrase française.", "Une autre phrase."])]
    translations = {
        hash_text("Une phrase française."): "A French sentence.",
        hash_text("Une autre phrase."): "Another sentence.",
    }
    out = tmp_path / "b.pdf"
    write_pdf("Essai", chapters, translations, out)
    data = out.read_bytes()
    assert data[:5] == b"%PDF-"
    assert len(data) > 2000


# ---- the book's author ----

def test_epub_records_the_author_in_its_metadata(tmp_path):
    chapters, translations, glosses = book_with_gloss()
    out = tmp_path / "b.epub"
    write_epub("Micromégas", chapters, translations, glosses, out, author="Voltaire")

    opf = zipfile.ZipFile(out).read("OEBPS/content.opf").decode("utf-8")
    assert "<dc:creator" in opf and "Voltaire" in opf
    assert 'property="role"' in opf and ">aut<" in opf   # marked as the author
    minidom.parseString(opf)   # still well-formed


def test_epub_omits_the_creator_when_no_author_is_given(tmp_path):
    chapters, translations, glosses = book_with_gloss()
    out = tmp_path / "b.epub"
    write_epub("Micromégas", chapters, translations, glosses, out)   # no author
    assert "<dc:creator" not in zipfile.ZipFile(out).read("OEBPS/content.opf").decode()


def test_an_author_with_xml_hostile_characters_stays_well_formed(tmp_path):
    chapters, translations, glosses = book_with_gloss()
    out = tmp_path / "b.epub"
    write_epub("T", chapters, translations, glosses, out, author="Dumas & <fils>")
    opf = zipfile.ZipFile(out).read("OEBPS/content.opf").decode()
    assert "&amp;" in opf and "&lt;fils&gt;" in opf
    minidom.parseString(opf)


def test_pdf_shows_the_author_on_the_title_page(tmp_path):
    chapters = [Chapter("I", None, [FR1])]
    html = _print_html("Micromégas", chapters, {hash_text(FR1): "x"}, author="Voltaire")
    assert '<div class="author">Voltaire</div>' in html
    # and it renders between the title and the "Lecteur bilingue" byline
    assert html.index("Micromégas") < html.index("Voltaire") < html.index("Lecteur bilingue")


def test_pdf_has_no_author_line_without_one(tmp_path):
    chapters = [Chapter("I", None, [FR1])]
    html = _print_html("Micromégas", chapters, {hash_text(FR1): "x"})
    assert 'class="author"' not in html
