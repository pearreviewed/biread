import json
import re

import pytest

from biread.cleanup import Chapter
from biread.render import (
    build_book_data,
    escape_html,
    fill,
    render_book,
    script_json,
    slugify,
)
from biread.translate import hash_text


def book_data_from(html):
    match = re.search(
        r'<script type="application/json" id="book-data">(.*?)</script>', html, re.S
    )
    return json.loads(match.group(1))


def test_slugify():
    assert slugify("Micromégas") == "micromegas"
    assert slugify("Les Fleurs du Mal!") == "les-fleurs-du-mal"
    assert slugify("日本語") == "book"


def test_fill_substitutes_placeholders():
    assert fill("a @@X@@ b @@Y@@", {"X": "1", "Y": "2"}) == "a 1 b 2"


def test_fill_does_not_rescan_substituted_values():
    # The book text is one of the values; a chain of str.replace would expand a
    # placeholder that happened to appear inside an earlier substitution.
    out = fill("@@A@@ then @@B@@", {"A": "text containing @@B@@", "B": "SCRIPT"})
    assert out == "text containing @@B@@ then SCRIPT"


def test_fill_rejects_unknown_placeholders():
    with pytest.raises(KeyError, match="@@MISSING@@"):
        fill("@@MISSING@@", {})


def test_escape_html():
    assert escape_html('A & B <c>') == "A &amp; B &lt;c&gt;"


def test_script_json_cannot_close_the_script_tag():
    payload = script_json({"fr": "</script><script>alert(1)</script>"})
    assert "</script>" not in payload
    assert "\\u003c" in payload
    assert json.loads(payload)["fr"] == "</script><script>alert(1)</script>"


def test_script_json_escapes_js_line_separators():
    # Legal inside a JSON string, but a raw newline inside a JS string literal.
    separators = "\u2028\u2029"
    payload = script_json({"fr": "a" + separators + "b"})
    assert not any(ch in payload for ch in separators)
    assert json.loads(payload)["fr"] == "a" + separators + "b"


def test_build_book_data_pairs_and_chapters(book):
    translations = {hash_text(t): f"[{t}]" for t in
                    ["Preamble.", "Le Départ", "Premier paragraphe.",
                     "Deuxième paragraphe.", "L'Arrivée", "Troisième paragraphe."]}
    data = build_book_data("Mon Livre", book, translations)

    assert [p["fr"] for p in data["pairs"]] == [
        "Preamble.", "Premier paragraphe.", "Deuxième paragraphe.", "Troisième paragraphe."
    ]
    assert data["pairs"][0]["en"] == "[Preamble.]"
    # Chapter I starts after the one-paragraph preamble; II after its two.
    assert [c["pair"] for c in data["chapters"]] == [1, 3]
    assert data["chapters"][0]["frEyebrow"] == "Chapitre I"
    assert data["chapters"][0]["enTitle"] == "[Le Départ]"
    assert data["publishedAvailable"] is False
    assert "pub" not in data["pairs"][0]


def test_missing_translations_render_as_empty(book):
    data = build_book_data("Mon Livre", book, {})
    assert all(p["en"] == "" for p in data["pairs"])


def test_published_column_is_carried_through(book):
    published = {hash_text("Premier paragraphe."): "The first paragraph."}
    data = build_book_data("Mon Livre", book, {}, published, "a note")
    assert data["publishedAvailable"] is True
    assert data["publishedNote"] == "a note"
    assert data["pairs"][1]["pub"] == "The first paragraph."
    assert data["pairs"][0]["pub"] == ""


def test_render_writes_a_self_contained_file(tmp_path, book):
    out = tmp_path / "deep" / "livre.html"
    render_book("Mon Livre", book, {}, out)
    html = out.read_text(encoding="utf-8")

    assert html.startswith("<!doctype html>")
    assert not re.search(r"@@[A-Z_]+@@", html)  # every placeholder consumed
    assert "src: url(data:font/woff2;base64," in html
    assert "http://" not in html and "https://" not in html
    assert not list(tmp_path.glob("**/*.tmp"))


def test_render_escapes_the_title(tmp_path, book):
    out = tmp_path / "x.html"
    render_book("Tom & <b>Jerry</b>", book, {}, out)
    html = out.read_text(encoding="utf-8")
    assert "<title>Tom &amp; &lt;b&gt;Jerry&lt;/b&gt;</title>" in html
    assert book_data_from(html)["titleFr"] == "Tom & <b>Jerry</b>"


def test_book_text_cannot_break_out_of_the_data_script(tmp_path):
    hostile = [Chapter(None, None, ["</script><img src=x onerror=alert(1)>"])]
    out = tmp_path / "x.html"
    render_book("Livre", hostile, {}, out)
    html = out.read_text(encoding="utf-8")
    assert "<img src=x" not in html
    assert book_data_from(html)["pairs"][0]["fr"] == "</script><img src=x onerror=alert(1)>"


def test_render_is_deterministic(tmp_path, book):
    first, second = tmp_path / "a.html", tmp_path / "b.html"
    render_book("Livre", book, {}, first)
    render_book("Livre", book, {}, second)
    assert first.read_bytes() == second.read_bytes()
