"""Reading a finished book back out of its own file.

The thing worth testing is fidelity, and it can be tested exactly: put a book
through the renderer, read it back, and the pairs and chapter headings derived
from the reconstruction must be the ones the file already carries. Anything less
means an EPUB that quietly disagrees with the book it came from — a chapter
heading gone, a paragraph facing the wrong translation — which is precisely the
failure nobody would notice until a reader opened it on a train.
"""
from __future__ import annotations

import json
import re

import pytest

from biread.cleanup import Chapter
from biread.errors import BireadError
from biread.export import epub
from biread.export.refit import book_from_html, formats_from_html
from biread.render import BOOK_DATA_RE, render_html
from biread.targets import ENGLISH, SPANISH
from biread.translate import hash_text

FR = ["Il y avait en Vestphalie un jeune garçon.",
      "Une autre phrase, plus courte.",
      "Et la troisième, qui ferme le chapitre."]
EN = ["There was in Westphalia a young boy.",
      "Another sentence, shorter.",
      "And the third, which closes the chapter."]


def a_book(**kwargs):
    """A book with everything the reconstruction has to survive: a leading
    section nobody numbered, two chapters, a titled one and a bare one, and a
    paragraph left with no counterpart at all."""
    chapters = [
        Chapter(None, None, ["Avertissement de l'éditeur."]),
        Chapter("I", "Le Départ", FR[:2]),
        Chapter("II", None, FR[2:]),
    ]
    translations = {hash_text(fr): en for fr, en in zip(FR, EN)}
    translations[hash_text("Le Départ")] = "The Departure"
    return render_html("Mon Livre", chapters, translations, **kwargs)


def data_of(html):
    return json.loads(BOOK_DATA_RE.search(html).group(2))


def test_a_book_read_back_lands_on_the_pairs_it_already_carries():
    html = a_book()
    title, chapters, translations, target = book_from_html(html)
    pairs, meta = epub._book_pairs(chapters, translations, target)

    was = data_of(html)
    assert title == was["titleFr"]
    assert pairs == [{"fr": p["fr"], "en": p["en"]} for p in was["pairs"]]
    assert meta == was["chapters"]


def test_the_paragraph_with_no_counterpart_stays_without_one():
    html = a_book()
    _, chapters, translations, _ = book_from_html(html)
    orphan = "Avertissement de l'éditeur."
    assert orphan in chapters[0].paragraphs
    assert translations[hash_text(orphan)] == ""


def test_the_book_is_read_in_its_own_language():
    _, _, _, target = book_from_html(a_book(target=SPANISH))
    assert target is SPANISH
    _, _, _, target = book_from_html(a_book())
    assert target is ENGLISH


def test_a_chapter_the_source_spelled_out_is_read_as_the_numeral_it_prints():
    """`Chapitre premier` is already `Chapitre I` by the time it is in the file,
    and the export must agree with the page a reader saw, not with the token the
    source happened to use."""
    html = render_html("L", [Chapter("premier", None, ["Une phrase."])], {})
    _, chapters, _, _ = book_from_html(html)
    assert chapters[0].number == "I"
    assert data_of(html)["chapters"][0]["frEyebrow"] == "Chapitre I"


def test_a_book_that_opens_on_its_first_chapter_gains_no_empty_section():
    html = render_html("L", [Chapter("I", None, ["Une phrase."])], {})
    _, chapters, _, _ = book_from_html(html)
    assert [c.number for c in chapters] == ["I"]


def test_reading_something_that_is_not_a_book_says_so():
    with pytest.raises(BireadError, match="carries no book data"):
        book_from_html("<!doctype html><p>hello</p>")


def test_an_unknown_format_is_refused_by_name(tmp_path):
    with pytest.raises(BireadError, match="no exporter for 'mobi'"):
        formats_from_html(a_book(), tmp_path, ["mobi"])


# ---- the real typesetting needs the browser engine; skipped without it ----

try:
    import playwright.sync_api  # noqa: F401
    HAS_BROWSER = True
except ImportError:
    HAS_BROWSER = False


@pytest.mark.skipif(not HAS_BROWSER, reason="EPUB export needs the [browser] extra")
def test_a_finished_book_is_typeset_into_a_readable_epub(tmp_path):
    import zipfile

    made = formats_from_html(a_book(), tmp_path, ["epub"], author="Voltaire")
    assert [(fmt, source, name) for fmt, source, name, _ in made] == [
        ("epub", "translation", "Mon Livre - bilingual reader.epub")]

    inside = zipfile.ZipFile(tmp_path / "Mon Livre - bilingual reader.epub")
    files = {n: inside.read(n).decode("utf-8") for n in inside.namelist()
             if n.endswith((".xhtml", ".opf"))}
    assert "pre-paginated" in files["OEBPS/content.opf"]
    assert "Voltaire" in files["OEBPS/content.opf"]
    body = "".join(files.values())
    assert "Vestphalie" in body and "Westphalia" in body
    assert "Le Départ" in body and "The Departure" in body


@pytest.mark.skipif(not HAS_BROWSER, reason="EPUB export needs the [browser] extra")
def test_the_french_page_faces_its_own_translation(tmp_path):
    """The pairing is the whole book, and it survives the round trip: whatever
    page the French lands on, the English facing it is the English for it."""
    import zipfile

    made = formats_from_html(a_book(), tmp_path, ["epub"])
    inside = zipfile.ZipFile(tmp_path / made[0][2])
    for name in inside.namelist():
        if not re.match(r"OEBPS/p\d+L\.xhtml", name):
            continue
        left = inside.read(name).decode("utf-8")
        right = inside.read(name.replace("L.xhtml", "R.xhtml")).decode("utf-8")
        for fr, en in zip(FR, EN):
            if fr[:20] in left:
                assert en[:20] in right, f"{fr[:20]!r} is facing the wrong page"


# ---- the command that gives any finished book its format -------------------
# A book built in the browser can carry no EPUB at the time it is made: both
# exporters measure real type in a headless browser, which a reader's tab cannot
# run. The book is on their disk afterwards, and the typesetting needs only that.

def _typeset(monkeypatch, blob=b"PK\x03\x04"):
    seen = {}

    def fake(html, out_dir, formats, author=""):
        seen["formats"], seen["author"] = formats, author
        return [(fmt, "translation", f"L.{fmt}", blob) for fmt in formats]

    monkeypatch.setattr("biread.export.refit.formats_from_html", fake)
    return seen


def test_a_book_built_in_a_browser_can_be_given_its_epub(tmp_path, monkeypatch):
    from biread import formats

    book = tmp_path / "la nausee - bilingual reader.html"
    book.write_text(a_book(), encoding="utf-8")
    _typeset(monkeypatch)

    assert formats.add_formats(book, ["epub"]) == [("epub", 4)]
    assert data_of(book.read_text(encoding="utf-8"))["downloads"][0]["format"] == "epub"


def test_both_formats_when_both_are_asked_for(tmp_path, monkeypatch):
    from biread import formats

    book = tmp_path / "b.html"
    book.write_text(a_book(), encoding="utf-8")
    seen = _typeset(monkeypatch)
    formats.main([str(book), "--pdf"])
    assert seen["formats"] == ["epub", "pdf"]
    assert [d["format"] for d in data_of(book.read_text(encoding="utf-8"))["downloads"]] == \
        ["epub", "pdf"]


def test_a_book_that_already_carries_it_is_left_alone(tmp_path, monkeypatch, capsys):
    from biread import formats

    book = tmp_path / "b.html"
    book.write_text(a_book(downloads=[("epub", "translation", "L.epub", b"PK")]),
                    encoding="utf-8")
    was = book.read_text(encoding="utf-8")
    _typeset(monkeypatch)
    assert formats.main([str(book)]) == 0
    assert book.read_text(encoding="utf-8") == was
    assert "already carries it" in capsys.readouterr().out


def test_the_source_file_you_built_from_is_refused_by_name(tmp_path, capsys):
    from biread import formats

    source = tmp_path / "la nausee.html"
    source.write_text("<html><body><p>Chapitre I</p></body></html>", encoding="utf-8")
    assert formats.main([str(source)]) == 1
    err = capsys.readouterr().err
    assert "la nausee.html is not a book biread made" in err
    assert "the finished HTML a build hands you" in err


def test_a_file_that_is_not_there_says_so(tmp_path, capsys):
    from biread import formats

    assert formats.main([str(tmp_path / "nowhere.html")]) == 2
    assert "No file at" in capsys.readouterr().err
