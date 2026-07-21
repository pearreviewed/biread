"""Smoke tests for the reader itself, driven in a real browser.

Everything else in the suite tests Python. The reader is where the expensive
bugs have lived — pagination measured against a box that was not laid out yet,
a drag target destroyed mid-gesture, a layout mode chosen from a stale width —
and none of them are reachable without a rendering engine.

Requires `pip install -e ".[browser]"` plus `playwright install chromium`;
skipped entirely when that is not present.
"""
import re

import pytest

from biread.cleanup import Chapter
from biread.render import render_book
from biread.translate import hash_text

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed"
).sync_playwright

SHORT_FR = "Une phrase française assez courte pour en tenir plusieurs sur une page."
SHORT_EN = "A French sentence short enough to fit several of them on one page."
# Deliberately taller than any page. Each sentence is numbered so that two
# different slices of it can never be byte-identical — otherwise a test that
# reassembles the parts cannot tell a dropped part from a repeated one.
TALL_FR = " ".join(f"{SHORT_FR} [fr-{n}]" for n in range(90))
TALL_EN = " ".join(f"{SHORT_EN} [en-{n}]" for n in range(90))


def build_reader(tmp_path_factory, published: bool):
    paragraphs = [f"{SHORT_FR} ({n})" for n in range(24)]
    paragraphs.insert(12, TALL_FR)
    chapters = [
        Chapter(None, None, [f"{SHORT_FR} (préambule)"]),
        Chapter("I", "Le Départ", paragraphs[:13]),
        Chapter("II", "L'Arrivée", paragraphs[13:]),
    ]

    translations, publications = {}, {}
    for chapter in chapters:
        if chapter.title:
            translations[hash_text(chapter.title)] = f"[{chapter.title}]"
        for paragraph in chapter.paragraphs:
            english = TALL_EN if paragraph == TALL_FR else f"{SHORT_EN} ({len(paragraph)})"
            translations[hash_text(paragraph)] = english
            # Published prose runs longer, which is what makes it a separate
            # constraint on where pages break.
            publications[hash_text(paragraph)] = english + " " + english

    out = tmp_path_factory.mktemp("reader") / "book.html"
    render_book(
        "Livre d'Essai", chapters, translations, out,
        publications if published else None, "a note" if published else "",
    )
    return out


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


def open_reader(browser, path, width=1280, height=900):
    page = browser.new_page(viewport={"width": width, "height": height})
    page.goto(path.as_uri())
    page.wait_for_function(
        "() => { const c = document.getElementById('counter');"
        "return c && c.textContent && !c.textContent.includes('+'); }",
        timeout=15000,
    )
    return page


@pytest.fixture(scope="module")
def reader(browser, tmp_path_factory):
    page = open_reader(browser, build_reader(tmp_path_factory, published=False))
    yield page
    page.close()


@pytest.fixture(scope="module")
def reader_with_published(browser, tmp_path_factory):
    page = open_reader(browser, build_reader(tmp_path_factory, published=True))
    yield page
    page.close()


def spread_count(page):
    return int(page.inner_text("#counter").split("/")[1].strip())


def current_spread(page):
    return int(page.inner_text("#counter").split("/")[0].strip())


def rewind(page):
    """Return to the first spread. The page is shared across the module, so a
    test that cares about position has to establish its own."""
    page.evaluate("document.getElementById('counter-input').blur()")
    for _ in range(6):
        page.evaluate(
            "document.dispatchEvent(new KeyboardEvent('keydown',"
            "{key:'ArrowLeft',shiftKey:true,bubbles:true}))"
        )
        page.wait_for_timeout(220)


def test_book_opens_paginated(reader):
    assert spread_count(reader) > 1
    assert reader.locator("#stage-wrap .page-left p.pair-fr").count() >= 1
    assert reader.locator("#stage-wrap .page-right p.pair-en").count() >= 1


def test_short_paragraphs_share_a_page(reader):
    # Guards the zero-width-probe bug, which silently put one paragraph on
    # every spread even though several fit. Spread 1 is the one-paragraph
    # preamble, so look across the opening stretch of the book.
    most = reader.evaluate(
        """async () => {
          const wait = ms => new Promise(r => setTimeout(r, ms));
          let most = 0;
          for (let i = 0; i < 6; i++) {
            most = Math.max(most, document.querySelectorAll(
              '#stage-wrap .page-left p.pair-fr').length);
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
            await wait(660);
          }
          return most;
        }"""
    )
    assert most > 1


def test_no_page_clips_unless_it_holds_a_single_paragraph(reader):
    findings = reader.evaluate(
        """() => {
          const bad = [];
          for (const p of document.querySelectorAll('#stage-wrap .page')) {
            if (p.classList.contains('leaf-face')) continue;
            const clipped = p.scrollHeight > p.clientHeight + 1;
            const paras = p.querySelectorAll('p.pair').length;
            if (clipped && paras > 1) bad.push({ paras, over: p.scrollHeight - p.clientHeight });
          }
          return bad;
        }"""
    )
    assert findings == []


def test_a_paragraph_taller_than_a_page_continues_instead_of_scrolling(reader):
    rewind(reader)
    result = reader.evaluate(
        """async () => {
          const wait = ms => new Promise(r => setTimeout(r, ms));
          let continuations = 0, clipped = 0, flush = true;
          for (let i = 0; i < 25; i++) {
            for (const p of document.querySelectorAll('#stage-wrap .page:not(.leaf-face)')) {
              if (p.scrollHeight > p.clientHeight + 1) clipped++;
            }
            for (const p of document.querySelectorAll('#stage-wrap p.pair.continued')) {
              continuations++;
              if (getComputedStyle(p).textIndent !== '0px') flush = false;
            }
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
            await wait(660);
          }
          return { continuations, clipped, flush };
        }"""
    )
    assert result["continuations"] > 0, "the over-tall paragraph should span spreads"
    assert result["clipped"] == 0, "a book reader must never need scrolling"
    assert result["flush"] is True, "a resumed paragraph starts flush, not indented"


def test_splitting_a_paragraph_loses_no_text(reader):
    # The split point is chosen by binary search and snapped to a word boundary
    # in each column independently. Reassembling the parts has to give the
    # original back — no dropped or duplicated words at the seam.
    rewind(reader)
    report = reader.evaluate(
        """async () => {
          const wait = ms => new Promise(r => setTimeout(r, ms));
          const norm = s => s.replace(/\\s+/g, ' ').trim();
          const parts = new Map();     // "spread:pair" -> text, so a repeated
                                       // sentence is never mistaken for a dupe
          for (let i = 0; i < 30; i++) {
            const spread = document.getElementById('counter').textContent.split('/')[0].trim();
            for (const p of document.querySelectorAll('#stage-wrap .page-left p.pair-fr')) {
              parts.set(spread + ':' + p.dataset.pair, p.textContent);
            }
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
            await wait(660);
          }
          const collected = new Map();
          for (const [key, text] of [...parts].sort(
                 (a, b) => Number(a[0].split(':')[0]) - Number(b[0].split(':')[0]))) {
            const pair = key.split(':')[1];
            collected.set(pair, (collected.get(pair) || []).concat([text]));
          }
          const PAIRS = JSON.parse(document.getElementById('book-data').textContent).pairs;
          const split = [], broken = [];
          for (const [pair, pieces] of collected) {
            if (pieces.length < 2) continue;
            split.push(Number(pair));
            if (norm(pieces.join(' ')) !== norm(PAIRS[pair].fr)) broken.push(Number(pair));
          }
          return { split, broken };
        }"""
    )
    assert report["split"], "expected at least one paragraph to be split across spreads"
    assert report["broken"] == [], "reassembled parts must equal the original paragraph"


def test_arrow_key_turns_the_page(reader):
    rewind(reader)
    before = current_spread(reader)
    reader.keyboard.press("ArrowRight")
    reader.wait_for_timeout(800)
    assert current_spread(reader) == before + 1


def test_shift_arrow_jumps_ten_spreads(reader):
    rewind(reader)
    before = current_spread(reader)
    reader.keyboard.press("Shift+ArrowRight")
    reader.wait_for_timeout(600)
    assert current_spread(reader) == min(before + 10, spread_count(reader))


def test_english_column_is_tagged_english_for_hyphenation(reader):
    # lang drives `hyphens: auto`; inheriting lang="fr" hyphenates English
    # with French syllabification and shifts every line count.
    assert reader.get_attribute("#stage-wrap .page-left p.pair-fr", "lang") == "fr"
    assert reader.get_attribute("#stage-wrap .page-right p.pair-en", "lang") == "en"


def test_bookmarks_persist_as_a_position_in_the_book(reader):
    reader.evaluate("localStorage.clear()")
    reader.click("#bm-star")
    reader.wait_for_timeout(200)
    stored = reader.evaluate(
        "JSON.parse(localStorage.getItem('biread:' + "
        "JSON.parse(document.getElementById('book-data').textContent).slug + ':bookmarks'))"
    )
    # A spread index would move when the window or font size changes; a pair index does not.
    assert stored["v"] == 2
    assert isinstance(stored["pairs"], list) and len(stored["pairs"]) == 1
    reader.click("#bm-star")


def test_narrow_viewport_switches_to_the_stacked_layout(browser, tmp_path_factory):
    page = open_reader(browser, build_reader(tmp_path_factory, published=False))
    assert page.locator("#stage-wrap .book-desk").count() == 1

    page.set_viewport_size({"width": 375, "height": 800})
    page.wait_for_selector("#stage-wrap .book-mobile", timeout=10000)
    assert page.locator("#stage-wrap .page-left").count() == 0
    assert page.locator("#stage-wrap .mobile-pair").count() >= 1
    page.close()


def test_published_toggle_swaps_english_without_moving_the_french(reader_with_published):
    page = reader_with_published
    french_before = page.inner_text("#stage-wrap .page-left")
    english_before = page.inner_text("#stage-wrap .page-right")

    page.click("#seg-published")
    page.wait_for_timeout(500)

    assert page.inner_text("#stage-wrap .page-left") == french_before, "French page must not change"
    assert page.inner_text("#stage-wrap .page-right") != english_before, "English page should swap"
    assert page.get_attribute("#seg-published", "aria-pressed") == "true"


def test_published_column_stays_reachable_when_it_runs_long(reader_with_published):
    # Pagination measures the generated translation only, so a longer published
    # column may overflow — including on pages holding several paragraphs. The
    # guarantee is not that it fits, but that it is never cut off unreachably.
    findings = reader_with_published.evaluate(
        """() => {
          const bad = [];
          for (const p of document.querySelectorAll('#stage-wrap .page:not(.leaf-face)')) {
            if (p.scrollHeight > p.clientHeight + 1
                && getComputedStyle(p).overflowY !== 'auto') bad.push(p.className);
          }
          return bad;
        }"""
    )
    assert findings == []


def test_the_published_segment_stays_disabled_without_a_published_text(reader):
    assert reader.get_attribute("#seg-published", "aria-disabled") == "true"
    assert reader.is_disabled("#seg-published")


def open_finder(page):
    page.click("#counter")
    page.wait_for_selector("#counter-input:not([hidden])")


def test_the_counter_opens_a_page_field(reader):
    rewind(reader)
    open_finder(reader)
    assert reader.is_hidden("#counter")
    assert reader.input_value("#counter-input") == "1"     # where you are, to edit


def test_typing_a_page_goes_there(reader):
    rewind(reader)
    open_finder(reader)
    reader.fill("#counter-input", "7")
    reader.press("#counter-input", "Enter")
    reader.wait_for_timeout(400)
    assert current_spread(reader) == 7
    assert reader.is_hidden("#counter-input")


def test_escape_leaves_the_page_alone(reader):
    rewind(reader)
    before = current_spread(reader)
    open_finder(reader)
    reader.fill("#counter-input", "9")
    reader.press("#counter-input", "Escape")
    reader.wait_for_timeout(200)
    assert current_spread(reader) == before
    assert reader.is_hidden("#counter-input")


def test_clicking_away_cancels(reader):
    rewind(reader)
    before = current_spread(reader)
    open_finder(reader)
    reader.fill("#counter-input", "9")
    reader.evaluate("document.getElementById('counter-input').blur()")
    reader.wait_for_timeout(200)
    assert current_spread(reader) == before
    assert reader.is_hidden("#counter-input")


def test_arrow_keys_edit_the_field_instead_of_turning_the_page(reader):
    # The reader steers on arrows. A caret moving inside the field must not also
    # move the book underneath it.
    rewind(reader)
    before = current_spread(reader)
    open_finder(reader)
    reader.fill("#counter-input", "5")
    for key in ("ArrowLeft", "ArrowRight", "ArrowLeft", "ArrowRight"):
        reader.press("#counter-input", key)
    reader.wait_for_timeout(200)
    assert current_spread(reader) == before
    reader.press("#counter-input", "Enter")
    reader.wait_for_timeout(400)
    assert current_spread(reader) == 5


def test_a_page_past_the_end_lands_on_the_last_one(reader):
    rewind(reader)
    open_finder(reader)
    reader.fill("#counter-input", "9999")
    reader.press("#counter-input", "Enter")
    reader.wait_for_timeout(600)
    assert current_spread(reader) == spread_count(reader)


def test_junk_in_the_field_does_nothing(reader):
    rewind(reader)
    before = current_spread(reader)
    open_finder(reader)
    reader.fill("#counter-input", "abc")
    reader.press("#counter-input", "Enter")
    reader.wait_for_timeout(300)
    assert current_spread(reader) == before


# ---- shareable position in the URL ----

def test_turning_a_page_updates_the_url_without_growing_history(reader):
    rewind(reader)
    before = reader.evaluate("history.length")
    reader.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))")
    reader.wait_for_timeout(650)
    assert re.match(r"^#p\d+$", reader.evaluate("location.hash")), "URL should carry the page"
    # replaceState, not pushState: Back must still leave the book, not walk it.
    assert reader.evaluate("history.length") == before


def test_opening_a_link_lands_on_that_page_and_skips_the_resume_banner(browser, tmp_path_factory):
    # A shared link means "take me here", so it wins over any saved position
    # and goes straight there rather than offering to resume.
    path = build_reader(tmp_path_factory, published=False)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(path.as_uri() + "#p8")
    page.wait_for_function(
        "() => { const c = document.getElementById('counter');"
        "return c && c.textContent && !c.textContent.includes('+'); }",
        timeout=15000,
    )
    page.wait_for_timeout(400)
    on_spread = page.evaluate("""() => {
      const els = [...document.querySelectorAll('#stage-wrap [data-pair]')].map(e => Number(e.dataset.pair));
      return { min: Math.min(...els), max: Math.max(...els) };
    }""")
    assert on_spread["min"] <= 8 <= on_spread["max"], "the linked pair should be on the open spread"
    assert not page.is_visible(".resume-banner")
    page.close()


def test_the_copy_link_button_copies_a_url_with_the_page(reader):
    rewind(reader)
    reader.evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}))")
    reader.wait_for_timeout(650)
    copied = reader.evaluate("""async () => {
      let got = null;
      navigator.clipboard.writeText = t => { got = t; return Promise.resolve(); };
      document.getElementById('link-btn').click();
      await new Promise(r => setTimeout(r, 100));
      return got;
    }""")
    assert copied and re.search(r"#p\d+$", copied), copied


# ---- gloss hover ----

GLOSS_FR = "Sur la table, il se leva et monta l'escalier tranquillement."


def build_glossed_reader(tmp_path_factory):
    from biread.gloss import GlossUnit

    def unit(surface, pos, gloss, inf="", pc=""):
        start = GLOSS_FR.index(surface)
        return GlossUnit(start, start + len(surface), pos, gloss, inf, pc)

    chapters = [Chapter("I", "Le Départ", [GLOSS_FR] + [f"{SHORT_FR} ({n})" for n in range(8)])]
    translations = {hash_text(p): SHORT_EN for c in chapters for p in c.paragraphs}
    translations[hash_text("Le Départ")] = "[Le Départ]"
    glosses = {hash_text(GLOSS_FR): [
        unit("Sur la table", "prep. phrase", "on the table"),
        unit("il se leva", "verb", "he rose", "se lever", "il s'est levé"),
        unit("monta", "verb", "climbed", "monter", "est monté"),
    ]}

    out = tmp_path_factory.mktemp("glossed") / "book.html"
    render_book("Livre Glosé", chapters, translations, out, None, "", glosses)
    return out


@pytest.fixture(scope="module")
def glossed(browser, tmp_path_factory):
    page = open_reader(browser, build_glossed_reader(tmp_path_factory))
    yield page
    page.close()


def test_units_become_hover_targets_only_in_the_french(glossed):
    assert glossed.locator("#stage-wrap .page-left .unit").count() == 3
    assert glossed.locator("#stage-wrap .page-right .unit").count() == 0


def test_the_paragraph_still_reads_as_the_original_text(glossed):
    # Units are offsets into the source, so the rendered text must be unchanged
    # — spans and the plain text between them reassemble it exactly.
    rendered = glossed.evaluate(
        "document.querySelector('#stage-wrap .page-left p.pair-fr').textContent"
    )
    assert rendered == GLOSS_FR


def test_hover_shows_the_gloss_with_the_verb_forms(glossed):
    glossed.hover("#stage-wrap .page-left .unit >> nth=1")
    glossed.wait_for_selector(".tip", timeout=3000)
    tip = glossed.inner_text(".tip")
    assert "il se leva" in tip
    assert "verb" in tip
    assert "he rose" in tip
    assert "from se lever" in tip          # infinitive, verbs only
    assert "passé composé: il s'est levé" in tip


def test_a_non_verb_shows_no_verb_lines(glossed):
    glossed.hover("#stage-wrap .page-left .unit >> nth=0")
    glossed.wait_for_selector(".tip", timeout=3000)
    tip = glossed.inner_text(".tip")
    assert "on the table" in tip
    assert "from " not in tip
    assert "passé composé" not in tip


def test_the_tooltip_stays_on_screen(glossed):
    glossed.hover("#stage-wrap .page-left .unit >> nth=0")
    glossed.wait_for_selector(".tip", timeout=3000)
    box = glossed.evaluate(
        """() => { const r = document.querySelector('.tip').getBoundingClientRect();
                   return {left: r.left, top: r.top, right: r.right, bottom: r.bottom}; }"""
    )
    assert box["left"] >= 0 and box["top"] >= 0
    assert box["right"] <= 1280 and box["bottom"] <= 900


def test_escape_dismisses_the_tooltip(glossed):
    glossed.hover("#stage-wrap .page-left .unit >> nth=0")
    glossed.wait_for_selector(".tip", timeout=3000)
    glossed.keyboard.press("Escape")
    assert glossed.locator(".tip").count() == 0


def test_a_book_without_glosses_has_no_hover_targets(reader):
    assert reader.locator("#stage-wrap .unit").count() == 0
