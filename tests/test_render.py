import base64
import json
import re

import pytest

from biread.cleanup import Chapter
from biread.render import (
    build_book_data,
    escape_html,
    download_name,
    fill,
    render_book,
    script_json,
    slugify,
)
from biread.targets import ENGLISH, SPANISH
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


def test_download_name_keeps_the_title_readable():
    # Unlike the slug, the download name keeps accents and spaces.
    assert download_name("Micromégas") == "Micromégas - bilingual reader"
    assert download_name("Les Fleurs du Mal") == "Les Fleurs du Mal - bilingual reader"


def test_download_name_strips_only_filesystem_hostile_characters():
    assert download_name('A/B: "C"?') == "AB C - bilingual reader"
    assert download_name("  spaced   out  ") == "spaced out - bilingual reader"
    assert download_name("") == "book - bilingual reader"


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


def test_english_default_carries_english_chrome(book):
    data = build_book_data("Mon Livre", book, {})
    assert data["lang"] == "en"
    assert data["chapters"][0]["enEyebrow"] == "Chapitre I".replace("Chapitre", "Chapter")
    assert data["ui"]["chapters"] == "Chapters"
    assert data["ui"]["bookmarks"] == "Bookmarks"


def test_target_localizes_eyebrow_ui_and_hyphenation(book):
    data = build_book_data("Mon Livre", book, {}, target=SPANISH)
    assert data["lang"] == "es"                        # drives the right column's hyphenation
    assert data["chapters"][0]["enEyebrow"] == "Capítulo I"
    assert data["ui"]["chapters"] == "Capítulos"
    assert data["ui"]["loading"] == "Abriendo el libro…"


def test_word_numbered_chapter_gets_a_numeral_eyebrow():
    # A French edition numbering its chapters in words must not surface in the
    # translation column as "Chapter premier": the number is shown as a numeral,
    # including the hyphenated compounds ("dix-septième" -> XVII).
    book = [Chapter("premier", "Le Début", ["Un paragraphe."]),
            Chapter("dix-septième", "Plus tard", ["Un autre paragraphe."])]
    data = build_book_data("Livre", book, {})
    assert [c["frEyebrow"] for c in data["chapters"]] == ["Chapitre I", "Chapitre XVII"]
    assert [c["enEyebrow"] for c in data["chapters"]] == ["Chapter I", "Chapter XVII"]


def test_the_masthead_stays_french_in_the_rendered_file(tmp_path, book):
    out = tmp_path / "es.html"
    render_book("Mon Livre", book, {}, out, target=SPANISH)
    html = out.read_text(encoding="utf-8")
    assert ">Lecteur bilingue<" in html          # masthead is not localized
    assert "Abriendo el libro" in html           # loading is


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


def _blob(html, fmt, source="translation"):
    match = re.search(
        rf'<script type="application/octet-stream" id="dl-{fmt}-{source}">(.*?)</script>',
        html, re.S,
    )
    return match.group(1) if match else None


def test_downloads_embed_as_lazy_blobs(tmp_path, book):
    epub, pdf = b"PK\x03\x04epub-bytes", b"%PDF-1.4 pdf-bytes"
    out = tmp_path / "x.html"
    render_book("Mon Livre", book, {}, out,
                downloads=[("epub", "translation", "Mon Livre.epub", epub),
                           ("pdf", "translation", "Mon Livre.pdf", pdf)])
    html = out.read_text(encoding="utf-8")

    # The menu metadata rides in the book data; the bytes do not.
    data = book_data_from(html)
    assert data["downloads"] == [
        {"format": "epub", "source": "translation", "filename": "Mon Livre.epub"},
        {"format": "pdf", "source": "translation", "filename": "Mon Livre.pdf"},
    ]
    # Each blob sits in its own script and decodes back to exactly the input.
    assert base64.b64decode(_blob(html, "epub")) == epub
    assert base64.b64decode(_blob(html, "pdf")) == pdf
    # The base64 is not dumped into the JSON that is parsed on every open.
    assert base64.b64encode(pdf).decode() not in json.dumps(data)


def test_both_editions_embed_when_a_published_translation_is_built(tmp_path, book):
    ai, pub = b"PK\x03\x04ai-epub", b"PK\x03\x04published-epub"
    out = tmp_path / "x.html"
    render_book("Mon Livre", book, {}, out, downloads=[
        ("epub", "translation", "Mon Livre (AI translation).epub", ai),
        ("epub", "published", "Mon Livre (published translation).epub", pub),
    ])
    html = out.read_text(encoding="utf-8")

    data = book_data_from(html)
    assert [d["source"] for d in data["downloads"]] == ["translation", "published"]
    # Each edition rides in its own source-tagged blob.
    assert base64.b64decode(_blob(html, "epub", "translation")) == ai
    assert base64.b64decode(_blob(html, "epub", "published")) == pub


def test_a_plain_build_has_no_download_control(tmp_path, book):
    out = tmp_path / "x.html"
    render_book("Mon Livre", book, {}, out)  # no --epub / --pdf
    html = out.read_text(encoding="utf-8")
    assert '<script type="application/octet-stream"' not in html
    assert "downloads" not in book_data_from(html)
    # The control ships hidden, so nothing shows without a built format.
    assert re.search(r'id="dl-btn"[^>]*\shidden', html)


def test_a_download_blob_cannot_close_its_script(tmp_path, book):
    # base64 has no '<', so even bytes spelling "</script>" cannot end the tag.
    out = tmp_path / "x.html"
    render_book("Livre", book, {}, out,
                downloads=[("epub", "translation", "L.epub", b"</script>bytes")])
    blob = _blob(out.read_text(encoding="utf-8"), "epub")
    assert "<" not in blob
    assert base64.b64decode(blob) == b"</script>bytes"


# ---- revise ----

def test_revise_embeds_config_and_a_per_pair_source_hash(book):
    data = build_book_data(
        "Mon Livre", book, {},
        revise={"provider": "anthropic", "model": "claude-x", "target": "English"},
    )
    assert data["revise"] == {
        "enabled": True,
        "provider": "anthropic",
        "model": "claude-x",
        "target": "English",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "style": "anthropic",
    }
    # A fix keys to the paragraph's source hash, so it survives a rebuild.
    assert all(p["h"] == hash_text(p["fr"]) for p in data["pairs"])


def test_revise_endpoint_and_style_follow_the_provider(book):
    for provider, style in [("openai", "openai"), ("openrouter", "openai"), ("ollama", "ollama")]:
        data = build_book_data("L", book, {}, revise={"provider": provider, "model": "m"})
        assert data["revise"]["style"] == style
        assert data["revise"]["endpoint"]  # a browser endpoint is recorded


def test_a_plain_build_carries_no_revise_config_or_hash(book):
    data = build_book_data("Mon Livre", book, {})
    assert "revise" not in data
    assert all("h" not in p for p in data["pairs"])


def test_only_a_revise_build_puts_a_provider_url_in_the_file(tmp_path, book):
    # The reader loads no external asset; the provider endpoint is present only
    # when --revise embedded it, so a plain book stays URL-free.
    plain = tmp_path / "plain.html"
    render_book("L", book, {}, plain)
    assert "api.anthropic.com" not in plain.read_text(encoding="utf-8")

    revised = tmp_path / "revise.html"
    render_book("L", book, {}, revised,
                revise={"provider": "anthropic", "model": "m", "target": "English"})
    assert "https://api.anthropic.com/v1/messages" in revised.read_text(encoding="utf-8")


def test_the_edits_link_control_ships_hidden(tmp_path, book):
    # Reader-JS reveals it only once a reader has made a correction to carry.
    out = tmp_path / "x.html"
    render_book("Mon Livre", book, {}, out)
    assert re.search(r'id="edits-btn"[^>]*\shidden', out.read_text(encoding="utf-8"))


# ---- re-wrapping a finished book -----------------------------------------
# A published book carries the reader it was built with, so a shelf that hands
# out files hands out old ones unless they are re-set in the current one.

def _rewrapped(**kwargs):
    from biread.render import render_html, rewrap

    book = [Chapter("I", "Titre", ["Il y avait en Vestphalie.", "Une autre phrase."])]
    html = render_html("Mon Livre", book, {}, downloads=[("epub", "translation", "L.epub", b"PK\x03\x04zz")])
    return html, rewrap(html, **kwargs)


def test_rewrapping_keeps_every_word_of_the_book():
    from biread.render import BOOK_DATA_RE

    before, after = _rewrapped()
    was = json.loads(BOOK_DATA_RE.search(before).group(2))
    now = json.loads(BOOK_DATA_RE.search(after).group(2))
    assert [p["fr"] for p in now["pairs"]] == [p["fr"] for p in was["pairs"]]
    assert now["chapters"] == was["chapters"]
    assert now["titleFr"] == was["titleFr"]


def test_rewrapping_carries_an_embedded_edition_across_untouched():
    before, after = _rewrapped()
    blob = re.search(r'<script type="application/octet-stream".*?</script>', before, re.S)
    assert blob and blob.group(0) in after, "the EPUB must survive the re-wrap"


def test_rewrapping_refreshes_labels_the_book_was_built_too_early_to_have():
    """The labels belong to the reader, not the book, and travel inside it — so an
    old book in a new reader would show blanks wherever a control was added."""
    from biread.render import BOOK_DATA_RE, rewrap

    before, _ = _rewrapped()
    stale = BOOK_DATA_RE.sub(
        lambda m: m.group(1) + json.dumps({
            **json.loads(m.group(2)), "ui": {"loading": "Opening…"}}) + m.group(3),
        before)
    now = json.loads(BOOK_DATA_RE.search(rewrap(stale)).group(2))
    assert now["ui"]["glossAdd"] == ENGLISH.ui["glossAdd"]
    assert len(now["ui"]) == len(ENGLISH.ui)


def test_the_offer_to_gloss_reaches_a_book_that_has_none():
    from biread.render import BOOK_DATA_RE

    _, after = _rewrapped(gloss_on_demand={"provider": "openrouter", "model": "m"})
    data = json.loads(BOOK_DATA_RE.search(after).group(2))
    assert data["gloss"]["enabled"] is True
    assert data["gloss"]["endpoint"].startswith("https://openrouter.ai")
    assert all("h" in pair for pair in data["pairs"]), "a bought gloss is kept by hash"
    assert data["gloss"]["functionWords"], "the reader needs the language, not just the URL"


def test_a_book_that_already_has_glosses_is_never_offered_them():
    from biread.gloss import GlossUnit
    from biread.render import BOOK_DATA_RE, render_html, rewrap

    book = [Chapter("I", None, ["Il y avait en Vestphalie."])]
    glosses = {hash_text("Il y avait en Vestphalie."): [
        GlossUnit(start=0, end=10, pos="verb", gloss="there was", infinitive="avoir", perfect="")]}
    html = render_html("L", book, {}, glosses=glosses)
    data = json.loads(BOOK_DATA_RE.search(
        rewrap(html, gloss_on_demand={"provider": "openrouter", "model": "m"})).group(2))
    assert "gloss" not in data, "there is nothing to buy, and an idle button lies"


def test_rewrapping_something_that_is_not_a_book_says_so():
    from biread.render import rewrap

    with pytest.raises(ValueError, match="not a built reader"):
        rewrap("<!doctype html><p>hello</p>")
