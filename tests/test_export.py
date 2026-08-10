import xml.dom.minidom as minidom
import zipfile

import pytest

from biread.cleanup import Chapter
from biread.export import epub, write_epub
from biread.targets import ENGLISH
from biread.translate import hash_text

FR1 = "Il s'appelait Micromégas, nom qui convient."
FR2 = "Les < & > périls de l'escalier."   # deliberately XML-hostile


def read_epub(path):
    z = zipfile.ZipFile(path)
    text = {n: z.read(n).decode("utf-8") for n in z.namelist()
            if n.endswith((".xhtml", ".opf", ".xml", ".css"))}
    return z, text


# The paginator needs a browser, but the layout it produces is a plain list of
# spreads. Everything downstream — the OPF, the pages, the zip — is pure and can
# be tested by handing _assemble a spread list directly.
def fake_spreads():
    chapter = {"frEyebrow": "Chapitre I", "frTitle": "Le Départ",
               "enEyebrow": "Chapter I", "enTitle": "The Departure"}
    return [
        {"chapter": chapter,
         "fr": [{"text": "Il s'appelait Micromégas.", "continued": False}],
         "en": [{"text": "He was called Micromégas.", "continued": False}]},
        {"chapter": None,
         "fr": [{"text": "Les < & > périls.", "continued": True}],
         "en": [{"text": "The < & > perils.", "continued": True}]},
    ]


# ---- the book flattened into pairs ----

def test_book_pairs_pair_french_with_english_and_mark_chapters():
    chapters = [Chapter("I", "Le Départ", [FR1, FR2])]
    translations = {hash_text(FR1): "He was called Micromégas.",
                    hash_text(FR2): "The perils of the staircase."}
    pairs, meta = epub._book_pairs(chapters, translations, ENGLISH)

    assert [p["fr"] for p in pairs] == [FR1, FR2]
    assert pairs[0]["en"] == "He was called Micromégas."
    assert meta == [{"pair": 0, "frEyebrow": "Chapitre I", "frTitle": "Le Départ",
                     "enEyebrow": "Chapter I", "enTitle": ""}]


# ---- the fixed-layout spread ----

def test_epub_is_a_fixed_layout_spread(tmp_path):
    out = tmp_path / "b.epub"
    epub._assemble("Micromégas", "Voltaire", fake_spreads(), out)

    _, files = read_epub(out)
    opf = files["OEBPS/content.opf"]
    assert '<meta property="rendition:layout">pre-paginated</meta>' in opf
    assert '<meta property="rendition:spread">both</meta>' in opf
    # the title page opens the book, then the spreads pair left/right
    assert opf.index('idref="titlepage"') < opf.index('idref="p0L"')
    assert 'idref="titlepage" properties="rendition:page-spread-center"' in opf
    assert 'idref="p0L" properties="page-spread-left"' in opf
    assert 'idref="p0R" properties="page-spread-right"' in opf
    assert opf.count("page-spread-left") == opf.count("page-spread-right") == 2


def test_french_is_on_the_left_page_english_on_the_right(tmp_path):
    out = tmp_path / "b.epub"
    epub._assemble("Micromégas", "", fake_spreads(), out)

    _, files = read_epub(out)
    left, right = files["OEBPS/p0L.xhtml"], files["OEBPS/p0R.xhtml"]
    assert 'class="page page-left"' in left and "pair-fr" in left
    assert "Il s'appelait Micromégas." in left
    assert 'class="page page-right"' in right and "pair-en" in right
    assert "He was called Micromégas." in right
    # the chapter heading is in both languages, one per page
    assert "Le Départ" in left and "The Departure" in right


def test_a_resumed_paragraph_is_flush_not_indented(tmp_path):
    out = tmp_path / "b.epub"
    epub._assemble("Micromégas", "", fake_spreads(), out)

    _, files = read_epub(out)
    # the second spread continues a split paragraph: it carries the flush class
    assert "pair-fr continued" in files["OEBPS/p1L.xhtml"]
    assert "pair-en continued" in files["OEBPS/p1R.xhtml"]


def test_the_spread_has_no_glosses(tmp_path):
    out = tmp_path / "b.epub"
    epub._assemble("Micromégas", "", fake_spreads(), out)

    _, files = read_epub(out)
    for name, body in files.items():
        if name.endswith(".xhtml"):
            assert "noteref" not in body and "footnote" not in body
            assert "gloss" not in body and 'class="unit"' not in body


def test_every_document_is_well_formed_even_with_hostile_text(tmp_path):
    # FR2/EN2 carry < & > on purpose.
    out = tmp_path / "b.epub"
    epub._assemble("Dumas & <Cie>", "Voltaire", fake_spreads(), out)

    _, files = read_epub(out)
    xml_files = [n for n in files if n.endswith((".xhtml", ".opf", ".xml"))]
    assert xml_files
    for name in xml_files:
        minidom.parseString(files[name])   # raises on malformed
    assert "&lt; &amp; &gt;" in files["OEBPS/p1L.xhtml"]


def test_the_mimetype_is_first_and_stored(tmp_path):
    out = tmp_path / "b.epub"
    epub._assemble("Micromégas", "", fake_spreads(), out)

    first = zipfile.ZipFile(out).infolist()[0]
    assert first.filename == "mimetype"
    assert first.compress_type == zipfile.ZIP_STORED
    assert zipfile.ZipFile(out).read("mimetype") == b"application/epub+zip"


# ---- the title page and the author ----

def test_the_title_page_shows_the_title_author_and_signature(tmp_path):
    out = tmp_path / "b.epub"
    epub._assemble("Micromégas", "Voltaire", fake_spreads(), out)

    page = zipfile.ZipFile(out).read("OEBPS/titlepage.xhtml").decode()
    assert 'class="page titlepage"' in page
    assert "Micromégas" in page and "Voltaire" in page and "Lecteur bilingue" in page


def test_the_title_page_omits_the_author_line_without_one(tmp_path):
    out = tmp_path / "b.epub"
    epub._assemble("Micromégas", "", fake_spreads(), out)

    page = zipfile.ZipFile(out).read("OEBPS/titlepage.xhtml").decode()
    assert 'class="tp-author"' not in page   # no empty byline


def test_the_author_is_recorded_in_the_metadata(tmp_path):
    out = tmp_path / "b.epub"
    epub._assemble("Micromégas", "Voltaire", fake_spreads(), out)

    opf = zipfile.ZipFile(out).read("OEBPS/content.opf").decode()
    assert "<dc:creator" in opf and "Voltaire" in opf
    assert 'property="role"' in opf and ">aut<" in opf   # marked as the author


def test_no_creator_element_without_an_author(tmp_path):
    out = tmp_path / "b.epub"
    epub._assemble("Micromégas", "", fake_spreads(), out)
    assert "<dc:creator" not in zipfile.ZipFile(out).read("OEBPS/content.opf").decode()


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


def test_pdf_shows_the_author_on_the_title_page():
    chapters = [Chapter("I", None, [FR1])]
    html = _print_html("Micromégas", chapters, {hash_text(FR1): "x"}, author="Voltaire")
    assert '<div class="author">Voltaire</div>' in html
    assert html.index("Micromégas") < html.index("Voltaire") < html.index("Lecteur bilingue")


def test_pdf_has_no_author_line_without_one():
    chapters = [Chapter("I", None, [FR1])]
    html = _print_html("Micromégas", chapters, {hash_text(FR1): "x"})
    assert 'class="author"' not in html


# ---- EPUB and PDF rendering both need the browser engine; skipped without it ----

try:
    import playwright.sync_api  # noqa: F401
    HAS_BROWSER = True
except ImportError:
    HAS_BROWSER = False


@pytest.mark.skipif(not HAS_BROWSER, reason="EPUB export needs the [browser] extra")
def test_write_epub_produces_a_real_fixed_layout_spread(tmp_path):
    chapters = [Chapter("I", "Le Départ", ["Une phrase française.", "Une autre phrase."])]
    translations = {
        hash_text("Une phrase française."): "A French sentence.",
        hash_text("Une autre phrase."): "Another sentence.",
    }
    out = tmp_path / "b.epub"
    write_epub("Essai", chapters, translations, out, ENGLISH, author="Voltaire")

    z, files = read_epub(out)
    assert "pre-paginated" in files["OEBPS/content.opf"]
    assert "OEBPS/p0L.xhtml" in files and "OEBPS/p0R.xhtml" in files
    assert "phrase française" in files["OEBPS/p0L.xhtml"]
    assert "French sentence" in files["OEBPS/p0R.xhtml"]
    for name in files:
        if name.endswith((".xhtml", ".opf")):
            minidom.parseString(files[name])


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


@pytest.mark.skipif(not HAS_BROWSER, reason="EPUB export needs the [browser] extra")
def test_no_page_holds_more_than_it_was_measured_to_hold(tmp_path):
    """The paginator measured in a fallback face and the book was set in Charis
    SIL, which is wider — so pages came out overfull, and `.page` clips what
    overruns, which means the last lines of about a page in three were cut off
    the book rather than merely crowded. Measuring is only worth anything if what
    was measured is what gets written, so this renders the emitted pages and
    holds them to their own page box."""
    import re as _re
    from playwright.sync_api import sync_playwright

    from biread.export.epub import PAGE_H, PAGE_W

    # Long paragraphs, so pages fill and a break has to be found inside one.
    body = [(" ".join(f"phrase numéro {n} d'un paragraphe français assez long pour "
                      f"remplir la page" for n in range(i * 12, i * 12 + 12)))
            for i in range(6)]
    chapters = [Chapter("I", "Le Départ", body)]
    translations = {hash_text(p): p.replace("phrase numéro", "sentence number")
                                  .replace("d'un paragraphe français assez long pour remplir la page",
                                           "of an English paragraph long enough to fill the page")
                    for p in body}
    out = tmp_path / "b.epub"
    write_epub("Essai", chapters, translations, out, ENGLISH)

    unpacked = tmp_path / "unpacked"
    zipfile.ZipFile(out).extractall(unpacked)
    pages = sorted((unpacked / "OEBPS").glob("p*.xhtml"))
    assert pages, "the book produced no pages at all"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": PAGE_W, "height": PAGE_H})
            overfull = []
            for path in pages:
                page.goto(path.resolve().as_uri())
                page.wait_for_function("() => document.fonts.check('23px \"Charis SIL\"')")
                spill = page.evaluate("""() => {
                  const box = document.querySelector('.page');
                  const cs = getComputedStyle(box);
                  const floor = box.getBoundingClientRect().bottom - parseFloat(cs.paddingBottom);
                  let worst = 0;
                  for (const el of box.querySelectorAll('p, .chapter-heading'))
                    worst = Math.max(worst, el.getBoundingClientRect().bottom - floor);
                  return Math.round(worst);
                }""")
                if spill > 0:
                    overfull.append((path.name, spill))
        finally:
            browser.close()

    assert not overfull, f"pages running past their own text box: {overfull}"
