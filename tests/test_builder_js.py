"""Smoke tests for the builder's screens, driven in a real browser.

The builder's engine boots Pyodide from a CDN, which is too slow and too online
for a suite that runs offline — so `builder_worker_stub.js` is served in its
place. The page reaches its engine by a relative `new Worker("worker.js")`, so
the swap needs no seam in the page: what is under test is the shipped
builder.html, unmodified.

What that leaves testable is exactly where the builder's bugs have been — a
price figure claiming more than it covered, a dangling clause, an ETA computed
from a clock that was never started, a control shown on the route that cannot
honour it. None of it is reachable without a rendering engine.

Requires `pip install -e ".[browser]"` plus `playwright install chromium`;
skipped entirely when that is not present.
"""
import functools
import http.server
import json
import shutil
import threading
from pathlib import Path

import pytest

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed"
).sync_playwright

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "biread" / "assets" / "fonts"
BOOK = b"Une phrase francaise, et puis une autre, pour faire un livre."


def scenario(**overrides) -> bytes:
    """A book whose text tells the stub engine how to answer."""
    return b"SCENARIO:" + json.dumps(overrides).encode() + b"\n---\n" + BOOK


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    """builder.html beside the stub engine, served over http — a Worker needs it."""
    root = tmp_path_factory.mktemp("builder")
    shutil.copy(ROOT / "web" / "builder.html", root / "builder.html")
    shutil.copy(Path(__file__).parent / "builder_worker_stub.js", root / "worker.js")
    for font in ("charis-sil-400.woff2", "charis-sil-400-italic.woff2"):
        shutil.copy(FONTS / font, root / font)
    # A finished book sits beside the builder exactly as the bundle serves it.
    # What is in it does not matter here — that it is fetchable, and arrives
    # named as a book rather than as a slug, is the whole of the promise.
    (root / "books").mkdir()
    for name in ("micromegas.html", "candide.html"):
        (root / "books" / name).write_bytes(b"<!doctype html><title>Un livre</title>")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *args, **kwargs: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/builder.html"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture
def page(browser, site):
    page = browser.new_page(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    page.goto(site)
    page.wait_for_selector("[data-route=translate]")
    yield page
    page.close()


# ---- helpers -------------------------------------------------------------

def text(page, selector):
    return page.eval_on_selector(selector, "e => e.textContent.trim()")


def hidden(page, selector):
    return page.eval_on_selector(selector, "e => e.hidden")


def showing(page, name):
    return not page.eval_on_selector(f"#s-{name}", "e => e.hidden")


def upload(page, selector, name, body=BOOK):
    page.set_input_files(selector, files=[{"name": name, "mimeType": "text/plain", "buffer": body}])


def to_settings(page, route="translate", body=BOOK, key="sk-or-v1-test"):
    """The common path: through step one, arriving at step two."""
    if route == "align":
        page.click("[data-route=align]")
    upload(page, "#f-orig", "livre.txt", body)
    if route == "align":
        upload(page, "#f-pub", "edition.txt", body)
    page.wait_for_function("!document.getElementById('to-settings').disabled")
    page.click("#to-settings")
    if key:
        page.fill("#key", key)
    page.wait_for_timeout(120)


# ---- the door ------------------------------------------------------------

def test_the_door_asks_for_the_book_first(page):
    """Who does the work is a question about a book, so the book comes first."""
    assert showing(page, "books")
    assert text(page, ".hero h1").startswith("The original on one page")
    assert page.eval_on_selector_all("#route button", "n => n.length") == 3
    assert page.locator("#engine").count() == 1
    assert not showing(page, "settings")


def test_who_does_the_work_is_asked_on_the_second_step(page):
    to_settings(page, key=None)
    assert showing(page, "settings")
    assert page.get_attribute("[data-engine=key]", "aria-pressed") == "true"
    assert not hidden(page, "#key-block")
    page.click("[data-engine=local]")
    assert page.get_attribute("[data-engine=local]", "aria-pressed") == "true"
    assert hidden(page, "#key-block")
    assert not hidden(page, "#local-block")
    # And back again, without having been sent through the door twice.
    page.click("[data-engine=key]")
    assert not hidden(page, "#key-block")


def test_the_local_path_asks_for_no_key(page):
    upload(page, "#f-orig", "livre.txt")
    page.wait_for_function("!document.getElementById('to-settings').disabled")
    page.click("#to-settings")
    page.click("[data-engine=local]")
    assert hidden(page, "#key-block")
    assert not hidden(page, "#local-block")
    assert "ollama pull" in text(page, "#setup")
    # Free, and it says so where the price would be.
    assert "Free" in text(page, "#fig")
    assert not page.eval_on_selector("#build", "e => e.disabled")


def test_the_theme_switches_and_is_remembered(page):
    assert page.eval_on_selector("html", "e => e.dataset.theme") in ("day", "night")
    page.click(".theme button[aria-label=Night]")
    assert page.eval_on_selector("html", "e => e.dataset.theme") == "night"
    page.reload()
    page.wait_for_selector("[data-route=translate]")
    assert page.eval_on_selector("html", "e => e.dataset.theme") == "night"
    page.click(".theme button[aria-label=Day]")


# ---- step one: the route and the files -----------------------------------

def test_the_second_file_is_asked_for_only_when_it_is_needed(page):
    assert hidden(page, "#pick-pub")
    page.click("[data-route=align]")
    assert not hidden(page, "#pick-pub")


def test_the_aligned_route_will_not_go_on_without_the_edition(page):
    page.click("[data-route=align]")
    upload(page, "#f-orig", "livre.txt")
    page.wait_for_timeout(200)
    assert page.eval_on_selector("#to-settings", "e => e.disabled")
    upload(page, "#f-pub", "edition.txt")
    page.wait_for_function("!document.getElementById('to-settings').disabled")


def test_a_file_card_says_it_takes_a_file_before_one_is_given(page):
    """Nothing on the card said it could be uploaded to but the words."""
    mask = lambda: page.eval_on_selector(
        "#pick-orig .sign", "n => getComputedStyle(n).maskImage")
    assert "svg" in mask()
    empty = mask()
    upload(page, "#f-orig", "livre.txt")
    page.wait_for_function("document.getElementById('pick-orig').classList.contains('has')")
    assert mask() != empty


def test_a_file_card_shows_what_the_file_says_about_itself(page):
    upload(page, "#f-orig", "livre.txt")
    page.wait_for_function(
        "document.getElementById('orig-about').textContent.indexOf('Reading') === -1")
    assert text(page, "#orig-name") == "livre.txt"
    about = text(page, "#orig-about")
    assert "Voltaire" in about and "34 ¶" in about


def test_a_file_card_stays_quiet_about_what_it_cannot_read(page):
    upload(page, "#f-orig", "livre.txt",
           scenario(inspect={"orig": {"title": None, "author": None, "language": None,
                                      "pages": None, "paragraphs": 12, "chars": 900}}))
    page.wait_for_function(
        "document.getElementById('orig-about').textContent.indexOf('Reading') === -1")
    # No byline invented from the filename, and no empty separators left behind.
    assert text(page, "#orig-about") == "12 ¶"


# ---- step two: key, model, and the gate ----------------------------------

def test_the_gate_marks_every_figure_as_an_approximation(page):
    to_settings(page)
    page.wait_for_function("document.getElementById('fig').textContent.indexOf('$') !== -1")
    assert text(page, "#fig").startswith("≈ $")
    detail = text(page, "#fig-detail")
    # Each component too, not only the headline.
    assert detail.count("≈ $") == 2, detail


def test_the_aligned_route_bars_a_provider_that_serves_no_embeddings(page):
    to_settings(page, route="align")
    assert page.eval_on_selector("[data-prov=anthropic]", "e => e.disabled")
    assert not page.eval_on_selector("[data-prov=openai]", "e => e.disabled")


def test_the_aligned_route_offers_the_hover_and_asks_for_a_model_only_then(page):
    to_settings(page, route="align")
    assert not hidden(page, "#gloss-block")
    assert not hidden(page, "#model-block")
    assert not hidden(page, "#model-why")
    page.uncheck("#gloss")
    page.wait_for_timeout(150)
    # With no glosses, the chat model does nothing on this route and is not asked for.
    assert hidden(page, "#model-block")


def test_the_aligned_gate_does_not_claim_the_reading_it_cannot_price(page):
    to_settings(page, route="align")
    page.wait_for_timeout(300)
    # No OpenRouter rate is known for the embedding model in a test, so the figure
    # covers the glosses alone and must say so rather than read as the whole bill.
    assert "reading is on top" in text(page, "#fig-of")
    assert "embedding rate" in text(page, "#fig-detail")


def test_the_build_button_waits_for_a_key(page):
    to_settings(page, key=None)
    assert page.eval_on_selector("#build", "e => e.disabled")
    page.fill("#key", "sk-or-v1-test")
    page.wait_for_function("!document.getElementById('build').disabled")


# ---- the proof page ------------------------------------------------------

def test_a_page_is_never_bought_without_being_asked_for(page):
    to_settings(page)
    assert text(page, "#proof-l") == ""
    assert "Translate one page" in text(page, ".empty")
    assert "fraction of a cent" in text(page, ".empty")


def test_reading_a_page_fills_the_spread_and_offers_the_next(page):
    to_settings(page)
    page.click(".empty .ghost")
    page.wait_for_selector("#proof-l p")
    assert "Sirius" in text(page, "#proof-l")
    assert "Sirius" in text(page, "#proof-r")
    assert text(page, "#proof-l-folio") == "1" and text(page, "#proof-r-folio") == "2"
    assert "Page 1 of 12" in text(page, "#proof-note")

    page.click("#proof-note button")
    page.wait_for_function(
        "document.getElementById('proof-note').textContent.indexOf('Page 2 of 12') !== -1")


def test_a_page_with_no_counterpart_says_so_rather_than_showing_blank(page):
    to_settings(page, route="align", body=scenario(sample={"total": 12, "cost": None, "glossCost": None,
                                                           "chars": 3102, "bookChars": 38974,
                                                           "blankTarget": True}))
    page.click(".empty .ghost")
    page.wait_for_selector("#proof-r p")
    assert "nothing in this edition" in text(page, "#proof-r")


def test_the_price_is_scaled_from_the_page_that_was_read(page):
    """The whole reason the sample is weighed: a constant fitted to one model ran
    1.8× light on the first model it had not seen."""
    to_settings(page)
    page.wait_for_function("document.getElementById('fig').textContent.indexOf('$') !== -1")
    counted = text(page, "#fig")
    page.click(".empty .ghost")
    page.wait_for_selector("#proof-l p")
    page.wait_for_function(
        "document.getElementById('fig-detail').textContent.indexOf('Scaled from') !== -1")

    # (0.0009 + 0.0055) translating and glossing 3102 chars, over a 38974-char book.
    assert text(page, "#fig") == "≈ $0.08"
    assert text(page, "#fig") != counted, "the measured figure should replace the counted one"


# ---- building, and what comes out ----------------------------------------

def test_the_progress_spread_fills_with_the_book_being_made(page):
    to_settings(page)
    page.click("#build")
    page.wait_for_function(
        "document.getElementById('bind-r').textContent.indexOf('Dutch') !== -1", timeout=15000)
    assert "hollandais" in text(page, "#bind-l")
    assert page.eval_on_selector_all("#bind-r .caret", "n => n.length") == 1


def test_the_finished_book_is_offered_with_its_cover_and_its_bill(page):
    to_settings(page)
    page.click("#build")
    page.wait_for_function("!document.getElementById('s-done').hidden", timeout=15000)
    assert text(page, "#cover-title") == "Micromégas"
    assert text(page, "#cover-by") == "Voltaire"
    assert "fr" in text(page, "#cover-pair")
    assert "KB" in text(page, "#download") or "MB" in text(page, "#download")
    assert "≈ $0.12 spent" in text(page, "#spent")


def test_the_book_downloads_under_its_own_name(page):
    to_settings(page)
    page.click("#build")
    page.wait_for_function("!document.getElementById('s-done').hidden", timeout=15000)
    with page.expect_download() as caught:
        page.click("#download")
    assert caught.value.suggested_filename == "livre - bilingual reader.html"


def test_a_build_that_fails_comes_back_and_says_why(page):
    to_settings(page, body=scenario(failOn="build", error="your key has no credit"))
    page.click("#build")
    page.wait_for_function("!document.getElementById('s-settings').hidden", timeout=15000)
    assert "your key has no credit" in text(page, "#settings-alert")


def test_a_file_that_cannot_be_read_says_so_on_the_step_that_asked_for_it(page):
    upload(page, "#f-orig", "livre.txt",
           scenario(failOn="inspect", error="livre.txt is not a readable EPUB"))
    page.wait_for_function("!document.getElementById('books-alert').hidden")
    assert "not a readable EPUB" in text(page, "#books-alert")


# ---- shape ---------------------------------------------------------------

@pytest.mark.parametrize("screen", ["books", "lookup", "settings", "binding", "done"])
def test_no_screen_scrolls_sideways_on_a_phone(page, screen):
    to_settings(page)
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate(f"show({screen!r})")
    page.wait_for_timeout(150)
    assert not page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")


def test_the_time_left_is_not_guessed_from_a_clock_that_never_started(page):
    """A progress message arriving before the build began once read
    'About 103279104 minutes left.'"""
    to_settings(page)
    page.evaluate("show('binding'); paintBinding({stage: 'translate', done: 412, total: 1842})")
    assert text(page, "#bind-eta") == "The tab can sit in the background."
    assert "412 of 1,842" in text(page, "#bind-at")


# ---- the shelf -----------------------------------------------------------

def to_shelf(page, slug="candide"):
    """Through the fork onto the shelf, with a book picked and fetched."""
    page.click("[data-route=shelf]")
    page.click(f".card[data-slug={slug!r}]")
    page.wait_for_function("!document.getElementById('to-settings').disabled")


def test_the_shelf_appears_only_once_the_engine_has_one(page):
    assert not hidden(page, "[data-route=shelf]")
    page.click("[data-route=shelf]")
    assert not hidden(page, "#shelf")
    assert hidden(page, "#files")


def test_a_card_shows_the_translator_the_wiki_names_and_nothing_more(page):
    page.click("[data-route=shelf]")
    card = ".card[data-slug=candide]"
    assert "Voltaire" in text(page, card)
    assert "Smollett · 1920" in text(page, card)
    assert "30" in text(page, f"{card} .facts")
    assert "about 3 min" in text(page, card)


def test_a_book_nobody_has_read_says_so_instead_of_claiming_coverage(page):
    page.click("[data-route=shelf]")
    unread = text(page, ".card[data-slug='80days']")
    assert "Nobody has read this one through" in unread
    assert "Abridged" in unread
    # And the one that has been read carries no such warning.
    assert "Nobody has read" not in text(page, ".card[data-slug=candide]")


def test_nothing_is_fetched_until_a_book_is_picked(page):
    page.click("[data-route=shelf]")
    assert page.eval_on_selector("#to-settings", "e => e.disabled")
    assert "Nothing is fetched" in text(page, "#books-foot")


def test_picking_a_book_fetches_both_editions_and_opens_the_way_on(page):
    to_shelf(page)
    assert "Both editions are here" in text(page, "#books-foot")
    assert "Chosen" in text(page, ".card[data-slug=candide]")
    page.click("#to-settings")
    assert showing(page, "settings")
    # The shelf is an aligned route: it asks for an embedding model, not a tier.
    assert not hidden(page, "#embed-block")


def test_the_shelf_route_prices_the_reading_not_a_translation(page):
    to_shelf(page)
    page.click("#to-settings")
    page.fill("#key", "sk-or-v1-test")
    page.wait_for_timeout(200)
    assert "read once by" in text(page, "#fig-detail")


def test_a_book_with_two_translations_lets_the_reader_choose(page):
    page.click("[data-route=shelf]")
    assert page.eval_on_selector_all(".versions", "n => n.length") == 0
    page.click(".card[data-slug=micromegas]")
    page.wait_for_selector(".versions")
    labels = page.eval_on_selector_all(".versions .pills button", "n => n.map(b => b.textContent)")
    assert labels == ["Phalen", "Fleming · 1906"]
    page.click(".versions .pills button:nth-child(2)")
    page.wait_for_function("!document.getElementById('to-settings').disabled")
    assert "Fleming · 1906" in text(page, ".card[data-slug=micromegas] .facts")


def test_searching_the_shelf_narrows_it_and_says_so_when_it_empties(page):
    page.click("[data-route=shelf]")
    page.fill("#shelf-find", "voltaire")
    assert page.eval_on_selector_all(".card", "n => n.length") == 2
    page.fill("#shelf-find", "dickens")
    assert page.eval_on_selector_all(".card", "n => n.length") == 0
    assert "Nothing on the shelf" in text(page, "#shelf-cards")


def test_a_filter_narrows_the_shelf_and_lets_go(page):
    page.click("[data-route=shelf]")
    page.click("#shelf-filters button:nth-child(2)")
    assert page.eval_on_selector_all(".card", "n => n.length") == 1
    page.click("#shelf-filters button:nth-child(2)")
    assert page.eval_on_selector_all(".card", "n => n.length") == 3


def test_the_pager_stays_away_while_the_shelf_fits_on_one_page(page):
    page.click("[data-route=shelf]")
    assert hidden(page, "#shelf-pager")


# ---- books already made --------------------------------------------------

def test_only_an_approved_book_is_offered_ready_to_read(page):
    page.click("[data-route=shelf]")
    offered = page.eval_on_selector_all(
        ".card .get", "n => n.map(b => b.closest('.card').dataset.slug)")
    assert offered == ["candide", "micromegas"], (
        "a card may hand over a book only where one was approved")
    assert "1.1 MB" in text(page, ".card[data-slug=micromegas] .get")


def test_the_ready_line_says_what_is_in_the_book_and_names_the_edition(page):
    page.click("[data-route=shelf]")
    said = text(page, ".card[data-slug=micromegas] .ready .say")
    # Two English editions are on offer, so the one inside is named; every other
    # clause is measured off the file rather than written by hand.
    assert "the French, a translation, and the published one (Phalen)" in said
    assert "hover glosses throughout" in said
    assert "EPUB and PDF inside" in said
    assert "Or build your own" in text(page, ".card[data-slug=micromegas] .ready")


def test_the_finished_book_does_not_sit_under_a_note_denying_it(page):
    page.click("[data-route=shelf]")
    card = text(page, ".card[data-slug=micromegas]")
    # Nobody has read the wiki pair this card would build. That is not a claim
    # about the book already made, and must not read as one.
    assert "Nobody has read the edition you would build here" in card
    assert "Nobody has read this one through" not in card
    order = page.eval_on_selector(
        ".card[data-slug=micromegas]",
        "c => [...c.children].findIndex(n => n.classList.contains('ready'))")
    marks = page.eval_on_selector(
        ".card[data-slug=micromegas]",
        "c => [...c.children].findIndex(n => n.classList.contains('say'))")
    assert order < marks, "the book in hand comes before anything about building one"


def test_taking_the_finished_book_neither_builds_it_nor_costs_a_key(page):
    page.click("[data-route=shelf]")
    with page.expect_download() as caught:
        page.click(".card[data-slug=micromegas] .get")
    assert caught.value.suggested_filename == "Micromégas - bilingual reader.html"
    # The download must not fall through to the card and start a build behind it.
    assert page.eval_on_selector_all(".card[aria-pressed=true]", "n => n.length") == 0
    assert not hidden(page, "#s-books")


def test_the_card_underneath_still_builds_the_book_yourself(page):
    page.click("[data-route=shelf]")
    page.click(".card[data-slug=micromegas] .name")
    page.wait_for_selector(".card[data-slug=micromegas][aria-pressed=true]")
    assert not hidden(page, ".card[data-slug=micromegas] .get"), (
        "a book already made must still be buildable — another English, another language"
    )


# ---- beyond the shelf ----------------------------------------------------

def test_the_lookup_is_its_own_screen_and_comes_back(page):
    page.click("[data-route=shelf]")
    page.click("[data-goto=lookup]")
    assert showing(page, "lookup")
    page.click("[data-goto=books]")
    assert showing(page, "books")


def test_a_search_reports_the_pair_it_found_and_the_side_it_did_not(page):
    page.click("[data-route=shelf]")
    page.click("[data-goto=lookup]")
    page.fill("#look-find", "germinal")
    page.click("#look-go")
    page.wait_for_selector(".hit .solid")
    found = text(page, ".hit:nth-child(1)")
    assert "Both editions found" in found and "Ellis · 1894" in found
    assert "40 chapters each — they agree" in found
    assert "Nobody has read this one through" in found
    missing = text(page, ".hit:nth-child(2)")
    assert "no free English translation" in missing
    # Neither library has it, and the card names both rather than only the wiki.
    assert "Standard Ebooks has none by Goncourt either" in missing
    assert "cannot be built" in missing


def look_up(page, query):
    page.click("[data-route=shelf]")
    page.click("[data-goto=lookup]")
    page.fill("#look-find", query)
    page.click("#look-go")


def test_a_search_says_how_much_it_is_not_showing_and_offers_it(page):
    """The lookup used to show four of eleven and keep the seven to itself."""
    look_up(page, "zola")
    page.wait_for_selector(".hit .solid")
    assert page.locator(".hit").count() == 4
    assert "4 works shown · at least 3 more" in text(page, "#look-out .caps")

    page.click("#look-out button.ghost")
    page.wait_for_function("document.querySelectorAll('.hit').length === 7")
    # The rest arrive beside the first four, not instead of them.
    assert "7 works shown" in text(page, "#look-out .caps")
    assert "more" not in text(page, "#look-out .caps")
    assert page.locator("#look-out button.ghost").count() == 0


def test_a_work_that_was_never_checked_says_so_rather_than_spinning(page):
    """A hit with a counterpart and no answer once read 'Looking for both
    editions…' for as long as the reader was willing to wait."""
    look_up(page, "zola")
    page.wait_for_selector(".hit .solid")
    page.click("#look-out button.ghost")
    page.wait_for_function("document.querySelectorAll('.hit').length === 7")
    last = text(page, ".hit:nth-child(7)")
    assert "never checked" in last
    assert "Looking for both editions" not in last


def test_a_missing_counterpart_offers_the_second_library_without_claiming_it(page):
    """Wikisource's interwiki links are sparse — Germinal and Candide carry none
    though English editions of both exist — so a miss there is not the end."""
    look_up(page, "le rêve")
    page.wait_for_selector(".hit .solid")
    card = text(page, ".hit")
    assert "Wikisource has no English edition" in card
    assert "Standard Ebooks has 2 by Émile Zola" in card
    assert "The Dream · tr. Eliza Chase" in card
    # Offered, never asserted: the reader is told plainly what this is not.
    assert "not a match we can vouch for" in card
    assert page.locator(".hit input[type=radio]").count() == 2
    # Nothing is chosen for the reader: preselecting one would be a quiet claim
    # that it is the right one, which is the thing this screen does not know.
    assert not page.is_checked(".hit input[type=radio]")
    assert page.eval_on_selector(".hit .solid", "e => e.disabled")


def test_taking_a_second_library_edition_records_where_it_came_from(page):
    look_up(page, "le rêve")
    page.wait_for_selector(".hit .solid")
    page.locator(".hit input[type=radio]").first.check()
    page.click(".hit .solid")
    page.wait_for_function("!document.getElementById('to-settings').disabled")
    found = page.evaluate("S.pick.book.found")
    assert found["source"] == "standardebooks"
    assert found["otherPage"] == "/ebooks/emile-zola/the-dream/eliza-chase"
    assert found["translator"] == "Eliza Chase"
    card = text(page, ".card[data-slug='found:Le Rêve']")
    assert "English from Standard Ebooks" in card
    # Its chapters there are uncounted until it is fetched, so nothing is claimed.
    assert "against" not in card


def test_the_edition_taken_is_the_one_the_reader_picked(page):
    look_up(page, "le rêve")
    page.wait_for_selector(".hit .solid")
    page.locator(".hit input[type=radio]").nth(1).check()
    page.click(".hit .solid")
    page.wait_for_function("!document.getElementById('to-settings').disabled")
    assert page.evaluate("S.pick.book.found.otherPage") == "/ebooks/emile-zola/germinal/havelock-ellis"


def test_a_book_still_in_copyright_is_a_plain_no_not_a_spinner(page):
    page.click("[data-route=shelf]")
    page.click("[data-goto=lookup]")
    page.fill("#look-find", "l'étranger camus")
    page.click("#look-go")
    page.wait_for_selector(".nothing")
    said = text(page, ".nothing")
    assert "still in copyright" in said
    assert "seventy years" in said
    assert "biread holds page names, never text" in said


def test_a_found_book_joins_the_shelf_marked_for_what_it_is(page):
    page.click("[data-route=shelf]")
    page.click("[data-goto=lookup]")
    page.fill("#look-find", "germinal")
    page.click("#look-go")
    page.wait_for_selector(".hit .solid")
    page.click(".hit .solid")
    page.wait_for_function("!document.getElementById('to-settings').disabled")
    assert showing(page, "books")
    card = text(page, ".card[data-slug='found:Germinal']")
    assert "Added by a reader" in card
    assert "Nobody has read this one through" in card
    # Its build time was unknown until both editions were counted, and now is not.
    assert "about" in card and "min" in card


def find_germinal(page, keep=False):
    """Look Germinal up and take it, keeping it or not."""
    page.click("[data-route=shelf]")
    page.click("[data-goto=lookup]")
    page.fill("#look-find", "germinal")
    page.click("#look-go")
    page.wait_for_selector(".hit .solid")
    if keep:
        page.check(".hit .check input")
    page.click(".hit .solid")
    page.wait_for_function("!document.getElementById('to-settings').disabled")


def back_to_the_shelf(page):
    """The same browser, opened again."""
    page.reload()
    page.wait_for_selector("[data-route=translate]")
    page.wait_for_selector("[data-route=shelf]:not([hidden])")
    page.click("[data-route=shelf]")


def test_a_found_book_is_kept_only_if_the_reader_asks(page):
    page.click("[data-route=shelf]")
    page.click("[data-goto=lookup]")
    page.fill("#look-find", "germinal")
    page.click("#look-go")
    page.wait_for_selector(".hit .solid")
    assert not page.is_checked(".hit .check input")
    assert "Saved in this browser" in text(page, ".hit")
    page.click(".hit .solid")
    page.wait_for_function("!document.getElementById('to-settings').disabled")
    back_to_the_shelf(page)
    assert page.locator(".card[data-slug='found:Germinal']").count() == 0


def test_a_kept_book_is_on_the_shelf_next_time_and_can_be_taken_off(page):
    find_germinal(page, keep=True)
    back_to_the_shelf(page)
    card = ".card[data-slug='found:Germinal']"
    page.wait_for_selector(card)
    assert "Kept by you" in text(page, card)
    # It was counted on the way in, and the figure came back with it.
    assert "about" in text(page, card) and "min" in text(page, card)
    # The shelf's own lede still counts only the books somebody has read.
    page.click("[data-goto=lookup]")
    assert "shelf is 3 books" in text(page, "#look-lede")
    page.click("[data-goto=books]")
    page.click(card + " .forget")
    assert page.locator(card).count() == 0
    back_to_the_shelf(page)
    assert page.locator(card).count() == 0


def test_a_book_divided_differently_says_so_rather_than_shrugging(page):
    """Le Père Goriot came back 4 chapters against 22 — real, and not the same
    thing as 47 against 46."""
    assert page.evaluate("agreement(40, 40)") == "40 chapters each — they agree."
    assert page.evaluate("agreement(47, 46)").endswith("two editions counting differently.")
    assert "divided quite differently" in page.evaluate("agreement(4, 22)")
    assert page.evaluate("agreement(1, 22)").startswith("1 chapter against 22")


def test_a_book_without_glosses_offers_them_rather_than_passing_over_it(page):
    page.click("[data-route=shelf]")
    said = text(page, ".card[data-slug=candide] .ready")
    assert "the French beside the published translation" in said
    assert "No hover glosses in this one" in said
    assert "on your own key" in said
    # The builder is the one place allowed to name a figure.
    assert "penny" in said


def test_a_book_that_has_glosses_is_not_offered_them_again(page):
    page.click("[data-route=shelf]")
    assert "No hover glosses" not in text(page, ".card[data-slug=micromegas] .ready")
