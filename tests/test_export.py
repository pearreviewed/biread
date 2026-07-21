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
