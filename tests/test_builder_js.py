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

Every test runs once per engine in `conftest.ENGINES` — Chromium and WebKit,
because Safari has faults Chromium cannot see.

Requires `pip install -e ".[browser]"` plus `playwright install chromium webkit`;
skipped entirely when that is not present.
"""
import functools
import http.server
import io
import json
import shutil
import threading
import unicodedata
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright not installed")

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
    assert text(page, ".hero h1").startswith("The original on the left")
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
    assert "hover translations only" in text(page, "#fig-of")
    assert "Matching the two editions is priced" in text(page, "#fig-detail")


def test_the_build_button_waits_for_a_key(page):
    to_settings(page, key=None)
    assert page.eval_on_selector("#build", "e => e.disabled")
    page.fill("#key", "sk-or-v1-test")
    page.wait_for_function("!document.getElementById('build').disabled")


def test_a_dead_build_button_says_what_it_is_waiting_for(page):
    """A faded button under a finished price, and nothing saying why: the reader
    pressed it, watched nothing happen, and had no way to learn that the field
    it wanted was a screen above."""
    to_settings(page, route="align", key=None)
    page.wait_for_function("document.getElementById('fig').textContent.indexOf('$') !== -1")
    assert page.eval_on_selector("#build", "e => e.disabled")
    assert not hidden(page, "#build-why")
    assert "key" in text(page, "#build-why")
    # And the line is the way there.
    page.click("#build-why")
    page.wait_for_timeout(600)
    assert page.evaluate("document.activeElement.id") == "key"
    assert page.eval_on_selector(
        "#key", "e => { const r = e.getBoundingClientRect(); return r.top > 0 && r.bottom < innerHeight; }")
    page.fill("#key", "sk-or-v1-test")
    page.wait_for_function("!document.getElementById('build').disabled")
    assert hidden(page, "#build-why")


def test_the_local_engine_is_never_asked_for_a_key_it_does_not_need(page):
    to_settings(page, key=None)
    page.click("[data-engine=local]")
    page.wait_for_timeout(150)
    assert not page.eval_on_selector("#build", "e => e.disabled")
    assert hidden(page, "#build-why")


# ---- the proof page ------------------------------------------------------

def test_a_page_is_never_bought_without_being_asked_for(page):
    to_settings(page)
    assert text(page, "#proof-l") == ""
    assert "Translate one page" in text(page, ".empty")
    assert "fraction of a cent" in text(page, ".empty")


def test_the_invitation_keeps_off_the_fold(page):
    """Type printed across a binding is the one thing a real book never does.

    The sentence keeps to the left page and what it asks for to the right, so
    both pages carry something and neither crosses the gutter.
    """
    to_settings(page)
    spread = page.eval_on_selector("#proof-spread", "e => e.getBoundingClientRect().toJSON()")
    fold = spread["x"] + spread["width"] / 2
    sides = {"left": 0, "right": 0}
    for box in page.eval_on_selector_all(
            ".empty p, .empty .ghost", "ns => ns.map(n => n.getBoundingClientRect().toJSON())"):
        assert box["x"] >= fold or box["x"] + box["width"] <= fold, "it sits on the fold"
        sides["right" if box["x"] >= fold else "left"] += 1
    assert sides["left"] and sides["right"]


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


def test_a_file_that_says_nothing_about_itself_is_named_by_its_filename(page):
    """"the original" is a claim about language the align route cannot make. A
    reader who brings two English editions of a French novel was told the one on
    the left was the original, in English. A filename claims only which file it is."""
    silent = scenario(inspect={"orig": {"title": None, "author": None, "language": None,
                                        "pages": None, "paragraphs": 700, "chars": 38974},
                               "pub": {"title": None, "author": None, "language": None,
                                       "pages": 89, "paragraphs": 689, "chars": 41000}})
    to_settings(page, route="align", body=silent)
    assert text(page, "#proof-l-title") == "livre.txt"
    assert text(page, "#proof-r-title") == "edition.txt"


def test_a_page_with_no_counterpart_says_so_rather_than_showing_blank(page):
    to_settings(page, route="align", body=scenario(sample={"total": 12, "cost": None, "glossCost": None,
                                                           "chars": 3102, "bookChars": 38974,
                                                           "blankTarget": True}))
    page.click(".empty .ghost")
    page.wait_for_selector("#proof-r p")
    column = text(page, "#proof-r")
    assert "Nothing in this edition answers to this page." in column
    # Once, at the head of the column. Said against each paragraph it read as
    # several faults rather than one page, and its closing dash wrapped every time.
    assert column.count("Nothing in this edition") == 1
    assert "—" not in column


def test_the_price_is_scaled_from_the_page_that_was_read(page):
    """The whole reason the sample is weighed: a constant fitted to one model ran
    1.8× light on the first model it had not seen."""
    to_settings(page)
    # Both halves weighed, which is the whole-book regime: with only the opening
    # glossed, the page read is the wrong ruler for the hover and stands aside.
    page.click("[data-scope=whole]")
    page.wait_for_function("document.getElementById('fig').textContent.indexOf('$') !== -1")
    counted = text(page, "#fig")
    page.click(".empty .ghost")
    page.wait_for_selector("#proof-l p")
    page.wait_for_function(
        "document.getElementById('fig-detail').textContent.indexOf('Scaled from') !== -1")

    # (0.0009 + 0.0055) translating and glossing 3102 chars, over a 38974-char book.
    assert text(page, "#fig") == "≈ $0.08"
    assert text(page, "#fig") != counted, "the measured figure should replace the counted one"


def test_the_hover_is_made_for_the_opening_by_default(page):
    """Glossing costs about four times translating and runs after both pages are
    written, so on a long book it is the whole of the wait. The book carries the
    protocol instead and fills itself in as it is read."""
    to_settings(page)
    assert page.get_attribute("[data-scope=opening]", "aria-pressed") == "true"
    assert "start reading in minutes" in text(page, "#gloss-scope-note")
    # How long an opening is belongs to the engine, which holds the paragraphs;
    # the page says only which of the two was asked for.
    assert page.evaluate("() => openingOnly()") is True

    page.click("[data-scope=whole]")
    assert page.evaluate("() => openingOnly()") is False
    assert "longest part of a build" in text(page, "#gloss-scope-note")

    # And no choice to make where there is no hover to make it about.
    page.uncheck("#gloss")
    assert hidden(page, "#gloss-scope")


# ---- building, and what comes out ----------------------------------------

def test_the_progress_spread_fills_with_the_book_being_made(page):
    to_settings(page)
    page.click("#build")
    page.wait_for_function(
        "document.getElementById('bind-r').textContent.indexOf('Dutch') !== -1", timeout=15000)
    assert "hollandais" in text(page, "#bind-l")
    assert page.eval_on_selector_all("#bind-r .caret", "n => n.length") == 1


def test_matching_shows_the_counterpart_it_placed(page):
    """The right page used to be empty for the whole of an aligning run: the route
    seeded the spread with the French and an empty string for every counterpart,
    so the left page turned and the right never did anything at all."""
    to_settings(page, route="align")
    page.click("#build")
    page.wait_for_function(
        "document.getElementById('bind-r').textContent.indexOf('Dutch') !== -1", timeout=15000)
    assert "hollandais" in text(page, "#bind-l")
    assert page.eval_on_selector_all("#bind-r .waiting", "n => n.length") == 0


def test_matching_says_what_the_right_page_is_waiting_for(page):
    """Until the first chapter lands there is no pair to show, so the left page
    turns on the count alone and the right says why it is empty."""
    page.evaluate(
        "show('binding');"
        "tookSeed([['Il ne parle que hollandais.', ''], ['Et pourtant.', '']]);"
        "paintBinding({stage: 'align', done: 5, total: 22})")
    assert "hollandais" in text(page, "#bind-l")
    assert "answers to it" in text(page, "#bind-r")


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


def test_replacing_a_refused_file_clears_the_complaint_about_it(page):
    upload(page, "#f-orig", "livre.txt", scenario(failOn="inspect", error="not readable"))
    page.wait_for_function("!document.getElementById('books-alert').hidden")
    upload(page, "#f-orig", "better.txt")
    page.wait_for_function("document.getElementById('books-alert').hidden")
    assert text(page, "#orig-about") != "Couldn't be read"


def test_the_card_of_an_unreadable_file_stops_saying_it_is_reading(page):
    # The alert and the card were contradicting each other: one said the file had
    # been refused, the other sat on "Reading…" for the rest of the session.
    upload(page, "#f-orig", "livre.txt",
           scenario(failOn="inspect", error="livre.txt did not come apart into paragraphs"))
    page.wait_for_function("!document.getElementById('books-alert').hidden")
    assert text(page, "#orig-about") == "Couldn't be read"


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


def test_a_stage_is_timed_from_its_own_start(page):
    """Glossing runs last, so a clock kept from the build's start charged the
    reading and the translating to the first few glosses: seven real minutes
    over four paragraphs quoted 'About 2806 minutes left' on a book that had
    well under an hour to go."""
    to_settings(page)
    page.evaluate(
        "show('binding');"
        "S.started = Date.now() - 7 * 60 * 1000;"
        "S.clock = { stage: 'translate', at: Date.now() - 6 * 60 * 1000, from: 0, rung: 10 };"
        "$('bind-eta').textContent = 'About 10 minutes left. The tab can sit in the background.';"
        "paintBinding({stage: 'gloss', done: 4, total: 1518})")
    # And the figure the last stage left behind goes with it: held over, it
    # quotes ten minutes for a pass nobody has timed.
    assert text(page, "#bind-eta") == "The tab can sit in the background."
    assert "4 of 1,518" in text(page, "#bind-at")


def test_the_wait_is_quoted_in_rungs_once_the_rate_holds_still(page):
    """Thirty paragraphs glossed in fifty-five seconds, with nine hundred to go,
    is a wait of about half an hour: said as half an hour, and said the same on
    the next message rather than counting down."""
    page.evaluate(
        "show('binding');"
        "S.clock = { stage: 'gloss', at: Date.now() - 55000, from: 0 };"
        "paintBinding({stage: 'gloss', done: 30, total: 930})")
    assert text(page, "#bind-eta") == "About 30 minutes left. The tab can sit in the background."
    page.evaluate("paintBinding({stage: 'gloss', done: 31, total: 930})")
    assert text(page, "#bind-eta") == "About 30 minutes left. The tab can sit in the background."


def test_glossing_says_the_two_pages_are_already_written(page):
    """The longest wait of the build comes after the book itself is made, and a
    reader watching a counter crawl through fifteen hundred paragraphs has no
    way of knowing that."""
    page.evaluate("show('binding'); paintBinding({stage: 'gloss', done: 4, total: 1518})")
    assert "Both pages are finished" in text(page, "#bind-note")
    page.evaluate("paintBinding({stage: 'translate', done: 4, total: 1518})")
    assert text(page, "#bind-note") == ""


def test_the_note_says_where_this_pass_ends(page):
    """On the default the pass stops at the opening and the book makes the rest
    under whoever reads it. A note promising the whole hover, over a counter
    that stops at forty, reads as a build that gave up partway."""
    page.evaluate("show('binding'); paintBinding({stage: 'gloss', done: 4, total: 40})")
    assert "as you read it" in text(page, "#bind-note")

    page.evaluate("S.glossScope = 'whole'; paintBinding({stage: 'gloss', done: 4, total: 1518})")
    assert "as you read it" not in text(page, "#bind-note")
    assert "Both pages are finished" in text(page, "#bind-note")


def spread_height(page):
    return page.eval_on_selector("#s-binding .spread", "e => Math.round(e.getBoundingClientRect().height)")


def test_the_book_being_made_keeps_one_size(page):
    """Sized by whatever paragraph had just landed, the spread went 236, 337,
    236 on three consecutive turns — a book jumping under the eyes of somebody
    watching it for an hour."""
    page.evaluate("show('binding')")
    long = "Donc, aujourd'hui, je regardais les bottes fauves d'un officier. " * 9
    seen = set()
    for n, source in enumerate(["Court.", "Une phrase de longueur ordinaire.", long, "Bref."]):
        page.evaluate("([s, i]) => paintSpread(s, s.toUpperCase(), i)", [source, n])
        seen.add(spread_height(page))
    assert len(seen) == 1, f"the spread changed size: {sorted(seen)}"
    # And it is the book's own proportions, not a box of whatever height suits.
    width = page.eval_on_selector("#s-binding .spread", "e => e.getBoundingClientRect().width")
    assert abs(width / seen.pop() - 7 / 5) < 0.02


def test_the_pages_keep_turning_while_the_glosses_are_made(page):
    """Nothing repainted the spread during glossing, which is the longest pass
    of the build: the screen a reader waits at longest was the one frozen."""
    page.evaluate(
        "show('binding');"
        "tookText([['Un.', 'One.'], ['Deux.', 'Two.'], ['Trois.', 'Three.']]);"
        "paintBinding({stage: 'gloss', done: 1, total: 3})")
    assert text(page, "#bind-l") == "Un."
    assert text(page, "#bind-r") == "One."
    page.evaluate("paintBinding({stage: 'gloss', done: 3, total: 3})")
    assert text(page, "#bind-l") == "Trois."
    assert text(page, "#bind-r") == "Three."
    # A page turning is a folio changing, not only words being replaced.
    assert text(page, "#bind-l-folio") == "5"
    assert text(page, "#bind-r-folio") == "6"


def test_glossing_a_book_with_nothing_made_yet_does_not_throw(page):
    """A resumed build can reach the glossing pass with no prose of its own to
    report, having bought every translation in an earlier session."""
    page.evaluate("show('binding'); S.made = []; paintBinding({stage: 'gloss', done: 8, total: 90})")
    assert "8 of 90" in text(page, "#bind-at")


# ---- what has already been paid for --------------------------------------

def test_a_paid_for_paragraph_outlives_the_tab(page):
    """Three hours of glossing used to end with a laptop lid and nothing to show.
    Every entry is written to the reader's own storage as it lands, under a hash
    of the book, and handed back to the engine next time."""
    page.evaluate("keepWork('abc.en', {one: 'un', two: 'deux'})")
    page.evaluate("() => flushWork()")
    page.reload()
    page.wait_for_selector("[data-route=translate]")
    held = page.evaluate("() => heldFor('abc.en')")
    assert held == {"one": "un", "two": "deux"}
    # Another language is another translation, and does not read the first's.
    assert page.evaluate("() => heldFor('abc.de')") == {}


def test_the_price_is_what_is_left_to_pay(page):
    """A book half built in an earlier session must not be quoted at the whole of
    itself, and the reader is told why the figure fell."""
    to_settings(page)
    page.evaluate(
        "S.estimate = {paragraphs: 100, pending: 40, translate_cost: 0.4, gloss_cost: 0.0,"
        " gloss_total: 100, gloss_done: 60, cost: 0.4};"
        "S.sample = null; paintPrice()")
    assert "60 passages of this book are already made" in text(page, "#fig-detail")
    # And the page read prices the remainder, not the book: a rate times what is
    # owed, where before it was a rate times everything.
    page.evaluate(
        "S.sample = {cost: 0.01, glossCost: 0.02, chars: 1000, bookChars: 100000};"
        "paintPrice()")
    assert page.evaluate("() => measured().translate") == pytest.approx(0.4, rel=1e-6)


def test_the_price_line_says_how_far_the_opening_reaches(page):
    """"For the opening" says nothing about how far it goes, and how far it goes
    is the difference between a chapter and four pages. The engine's own count
    for this book is on the line, so it cannot promise a stretch it will not
    make."""
    to_settings(page)
    page.evaluate(
        "S.estimate = {paragraphs: 1518, pending: 1518, translate_cost: 0.4,"
        " gloss_cost: 0.06, gloss_total: 85, cost: 0.46};"
        "S.sample = null; paintPrice()")
    assert "opening 85 passages" in text(page, "#fig-detail")

    page.click("[data-scope=whole]")
    page.evaluate(
        "S.estimate = {paragraphs: 1518, pending: 1518, translate_cost: 0.4,"
        " gloss_cost: 0.9, gloss_total: 1518, cost: 1.3};"
        "S.sample = null; paintPrice()")
    assert "opening" not in text(page, "#fig-detail")


# ---- the shelf -----------------------------------------------------------

def to_shelf(page, slug="candide"):
    """Through the fork onto the shelf, with a book picked and fetched.

    A card with a finished book behind it hands that file over when pressed;
    building the same book yourself is the small line under it.
    """
    page.click("[data-route=shelf]")
    card = f".card[data-slug={slug!r}]"
    own = page.locator(f"{card} .own")
    page.click(f"{card} .own" if own.count() else card)
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
    # How long a build takes is said wherever building is what is offered: on
    # the card's own action where no finished file exists, on the line under one
    # where it does — never beside the weight, which it would be mistaken for.
    # It is the figure the "under ten minutes" shelf is counting.
    assert "about 3 min" not in text(page, f"{card} .facts")
    assert "about 3 min" in text(page, f"{card} .own")
    assert "about 9 min" in text(page, ".card[data-slug='80days'] .act")


def test_a_book_nobody_has_read_says_so_instead_of_claiming_coverage(page):
    page.click("[data-route=shelf]")
    unread = text(page, ".card[data-slug='80days']")
    assert "Nobody has read this one through" in unread
    assert "Towle · 1873 · abridged" in unread
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
    page.click(".card[data-slug=micromegas] .own")
    page.wait_for_selector(".versions")
    labels = page.eval_on_selector_all(".versions .pills button", "n => n.map(b => b.textContent)")
    assert labels == ["Phalen", "Fleming · 1906"]
    page.click(".versions .pills button:nth-child(2)")
    page.wait_for_function("!document.getElementById('to-settings').disabled")
    assert "Fleming · 1906" in text(page, ".card[data-slug=micromegas] .facts")


def test_the_shelf_reads_alphabetically_as_the_line_beneath_it_says(page):
    """The books used to come out in the order they were added, under a line
    that called them alphabetical."""
    page.click("[data-route=shelf]")
    titles = page.eval_on_selector_all("#shelf-cards .card .name", "n => n.map(e => e.textContent)")
    assert titles == sorted(titles, key=str.lower)
    assert "alphabetical" in text(page, "#shelf-count")


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


def test_the_row_below_the_cards_keeps_its_place_across_categories(page):
    """It used to be dropped whenever a filter left one page, which took the
    rule and 50px of height out from under the cards as the reader switched."""
    page.click("[data-route=shelf]")
    tall = page.eval_on_selector("#shelf-pager", "n => n.getBoundingClientRect().height")
    assert not hidden(page, "#shelf-pager")
    assert "3 books" in text(page, "#shelf-count")
    page.click("#shelf-filters button:nth-child(2)")
    assert page.eval_on_selector("#shelf-pager", "n => n.getBoundingClientRect().height") == tall
    assert "1 book" in text(page, "#shelf-count")


def test_the_cards_in_a_row_end_level(page):
    """Left to their own heights they ended wherever their prose ran out, and a
    row of three finished on three different lines. The trade is deliberate: a
    card is now a little taller in one category than in another, which a filter
    can be seen doing — the ragged row was the worse of the two."""
    page.click("[data-route=shelf]")
    rows = {}
    for top, bottom in page.eval_on_selector_all(
            ".card", "n => n.map(c => { const r = c.getBoundingClientRect();"
                     "  return [Math.round(r.top), Math.round(r.bottom)]; })"):
        rows.setdefault(top, set()).add(bottom)
    assert rows, "no cards on the shelf"
    for top, bottoms in rows.items():
        assert len(bottoms) == 1, f"the row at {top} ends on {sorted(bottoms)}"


def test_the_tab_strip_is_the_same_size_on_every_route(page):
    """The shelf used to widen the whole step, so the three tabs grew under the
    finger that had just pressed one, and the note below them stood at a
    different height on each route."""
    boxes = []
    for route in ("translate", "align", "shelf"):
        page.click(f"[data-route={route}]")
        page.wait_for_timeout(80)
        boxes.append(page.evaluate(
            "() => ['#route', '#route-note'].map(s => {"
            "  const r = document.querySelector(s).getBoundingClientRect();"
            "  return [Math.round(r.left), Math.round(r.width), Math.round(r.height)];"
            "})"))
    assert boxes[0] == boxes[1] == boxes[2], boxes


def test_the_tab_strip_holds_its_height_in_a_face_it_was_not_drawn_in(page):
    """Pressing a tab sets its label in bold, and bold is wider — in the face the
    page falls back to before Charis SIL arrives, wide enough to break "Have a
    model translate it" over two lines, so the tab grew under the finger that had
    just pressed it. Every label is laid out at its bold width in both states,
    which is what has to hold in a face nobody chose."""
    page.add_style_tag(content="* { font-family: Georgia, 'Times New Roman', serif !important }")
    tall = []
    for route in ("translate", "align", "shelf"):
        page.click(f"[data-route={route}]")
        page.wait_for_timeout(80)
        tall.append(page.evaluate(
            "() => Math.round(document.getElementById('route').getBoundingClientRect().height)"))
    assert tall[0] == tall[1] == tall[2], tall


def test_the_route_note_is_set_to_the_width_of_the_tabs_it_explains(page):
    """At a measure of its own it broke mid-sentence with a third of the panel
    standing empty beside it."""
    seg, note = page.evaluate(
        "() => ['#route', '#route-note'].map(s =>"
        "  Math.round(document.querySelector(s).getBoundingClientRect().width))")
    assert seg == note, (seg, note)


# ---- books already made --------------------------------------------------

def test_only_an_approved_book_is_offered_ready_to_read(page):
    page.click("[data-route=shelf]")
    offered = page.eval_on_selector_all(
        ".card .act.ready", "n => n.map(b => b.closest('.card').dataset.slug)")
    assert offered == ["candide", "micromegas"], (
        "a card may hand over a book only where one was approved")
    assert "1.1 MB" in text(page, ".card[data-slug=micromegas] .act")
    # Every other card still says what it does, so no card is a dead panel.
    assert "Build it yourself" in text(page, ".card[data-slug='80days'] .act")


def test_the_ready_line_says_what_is_in_the_book_and_names_the_edition(page):
    page.click("[data-route=shelf]")
    said = text(page, ".card[data-slug=micromegas] .say")
    # Two English editions are on offer, so the one inside is named; every other
    # clause is measured off the file rather than written by hand. One line, and
    # one only — the rule beneath it stands level with its neighbours' or the
    # row reads as out of true.
    assert said == "French + Phalen · hover translations · EPUB + PDF"
    assert "Or build it yourself" in text(page, ".card[data-slug=micromegas]")


def test_the_finished_book_does_not_sit_under_a_note_denying_it(page):
    """Nobody has read the wiki pair this card would build. That is not a claim
    about the book already made, so it waits for the reader who asks to build
    one — and never reads as a warning about the file being handed over."""
    page.click("[data-route=shelf]")
    card = ".card[data-slug=micromegas]"
    assert "Nobody has read" not in text(page, card)
    page.click(f"{card} .own")
    page.wait_for_selector(f"{card} .more")
    assert "Nobody has read the edition you would build here" in text(page, f"{card} .more")
    assert "Nobody has read this one through" not in text(page, card)
    order = page.eval_on_selector(
        card, "c => [...c.children].findIndex(n => n.classList.contains('act'))")
    later = page.eval_on_selector(
        card, "c => [...c.children].findIndex(n => n.classList.contains('more'))")
    assert order < later, "the book in hand comes before anything about building one"


def test_taking_the_finished_book_neither_builds_it_nor_costs_a_key(page):
    page.click("[data-route=shelf]")
    with page.expect_download() as caught:
        page.click(".card[data-slug=micromegas] .name")
    # Normalized on both sides: Safari hands the name back decomposed (an `e`
    # and a separate accent), which is the same name and a different string.
    assert (unicodedata.normalize("NFC", caught.value.suggested_filename)
            == "Micromégas - bilingual reader.html")
    # Taking the file is not choosing the book: no build starts behind it.
    assert page.eval_on_selector_all(".card[aria-pressed=true]", "n => n.length") == 0
    assert not hidden(page, "#s-books")


def test_the_line_underneath_still_builds_the_book_yourself(page):
    page.click("[data-route=shelf]")
    page.click(".card[data-slug=micromegas] .own")
    page.wait_for_selector(".card[data-slug=micromegas][aria-pressed=true]")
    assert not hidden(page, ".card[data-slug=micromegas] .act.ready"), (
        "a book already made must still be buildable — another English, another language"
    )


def edge_contrast(page, box, side):
    """How strongly one edge of a box is painted, position by position.

    Read off a screenshot, because a border can be styled perfectly and never
    painted: Safari broke a shelf card across a column boundary and the piece
    below it came out with no top edge, while every computed style said it was
    there. Each position is measured against the pixel just outside the box, so
    it reads the same in day and night.
    """
    image = pytest.importorskip("PIL.Image", reason="pillow not installed")
    inset, reach = 24, 6  # past the rounded corners; deep enough to cross the border
    if side == "top":
        clip = {"x": box["x"] + inset, "y": box["y"] - 3,
                "width": box["width"] - 2 * inset, "height": reach}
    else:
        clip = {"x": box["x"] - 3, "y": box["y"] + inset,
                "width": reach, "height": box["height"] - 2 * inset}
    shot = image.open(io.BytesIO(page.screenshot(clip=clip))).convert("L")
    px = shot.load()
    width, height = shot.size
    if side == "top":
        return [max(abs(px[x, y] - px[x, 0]) for y in range(1, height)) for x in range(width)]
    return [max(abs(px[x, y] - px[0, y]) for x in range(1, width)) for y in range(height)]


def test_a_hovered_card_keeps_the_whole_of_its_frame(page):
    """The frame is one border: if the left edge is painted, so is the top.

    Judged against the card's own left edge rather than a number, since what
    counts as bright depends on the theme, the engine and the screen.
    """
    page.click("[data-route=shelf]")
    page.wait_for_selector(".card")
    # Solid frames only: a book nobody has read through is drawn dashed, and a
    # dash and a gap are the same reading as a border that is missing.
    cards = page.query_selector_all(".card:not(.unread)")
    assert cards, "no card with a solid frame to read"
    for card in cards:
        for state in ("at rest", "hovered"):
            if state == "hovered":
                card.hover()
                page.wait_for_timeout(300)
            box = card.bounding_box()
            top, left = edge_contrast(page, box, "top"), edge_contrast(page, box, "left")
            # The side first, or the comparison is vacuous: Safari once broke a
            # card across two columns, and the box it then reported enclosed the
            # whole flow, so both readings came back flat and everything
            # "passed". Healthy is 24 and up at rest, 150 and up hovered.
            assert min(left) > 12, f"{state}, the frame is not painted where it is read"
            assert min(top) > 0.5 * min(left), (
                f"{state}, the top of the frame goes missing where the side does not "
                f"(weakest top {min(top)}, weakest side {min(left)})"
            )
        page.mouse.move(2, 2)
        page.wait_for_timeout(150)


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
    assert "40 chapters each, so they agree" in found
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
    # Which library the English came from is a fact about that edition, so it is
    # said on the line naming it rather than on a badge of its own.
    assert "The Dream · tr. Eliza Chase · Standard Ebooks" in card
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
    assert page.evaluate("agreement(40, 40)") == "40 chapters each, so they agree."
    assert page.evaluate("agreement(47, 46)").endswith("two editions counting differently.")
    assert "divided quite differently" in page.evaluate("agreement(4, 22)")
    assert page.evaluate("agreement(1, 22)").startswith("1 chapter against 22")


def test_a_book_without_hover_translations_says_so_in_a_phrase(page):
    """The offer used to be made here, in a sentence with a price in it, and it
    ran to two lines on seven cards of eight. A card states the fact; the offer
    is met in the reader, whose header carries it."""
    page.click("[data-route=shelf]")
    assert text(page, ".card[data-slug=candide] .say") == \
        "French + published translation · no hover translations"
    assert "penny" not in text(page, ".card[data-slug=candide]")


def test_a_book_that_has_them_is_not_said_to_be_missing_them(page):
    page.click("[data-route=shelf]")
    assert "no hover translations" not in text(page, ".card[data-slug=micromegas]")


def test_a_card_says_on_its_face_what_the_book_is(page):
    """The one thing a reader picks a book on, in a sentence that stands alone —
    where a row of uppercase pills used to be. Two lines at most, so a card is
    sized by its book rather than by its blurb."""
    page.click("[data-route=shelf]")
    lead = page.eval_on_selector(
        ".card[data-slug=candide] .lead",
        "e => ({said: e.textContent, lines: Math.round(e.getBoundingClientRect().height"
        "                                              / parseFloat(getComputedStyle(e).lineHeight))})")
    assert lead["said"].startswith("A young man taught this is the best")
    assert lead["lines"] <= 2, lead
    # The pills are gone, and with them the shout: a book that is abridged says
    # so on the line naming the edition, in the card's own voice.
    assert page.locator(".card .mark").count() == 0
    assert "Towle · 1873 · abridged" in text(page, ".card[data-slug='80days'] .facts")
    # A book somebody looked up has no sentence written for it, and its card
    # invents none.
    assert page.locator(".card[data-slug='80days'] .lead").count() == 0


def test_a_card_opens_on_the_rest_of_it_without_moving_the_shelf(page):
    """The face carries one sentence; the rest opens downward under the pointer —
    over the row beneath, never displacing it, because a shelf that shifts as you
    read across it is the fault this one has been fixed for twice."""
    page.click("[data-route=shelf]")
    # Every card but the one under the pointer, which lifts 2px as it always has.
    # Measured down the document rather than down the window: reaching a card
    # near the foot of the viewport scrolls the page to it, and a scroll is not
    # the shelf moving. Reflow under the pointer is what this is watching for.
    where = lambda: page.eval_on_selector_all(
        ".card:not([data-slug=candide])",
        "n => n.map(c => Math.round(c.getBoundingClientRect().bottom + window.scrollY))")
    shut = where()
    assert page.eval_on_selector(
        ".card[data-slug=candide] .brief", "e => getComputedStyle(e).visibility") == "hidden"
    page.hover(".card[data-slug=candide]")
    page.wait_for_timeout(250)
    open_ = page.eval_on_selector(
        ".card[data-slug=candide] .brief",
        "e => ({seen: getComputedStyle(e).visibility, paint: getComputedStyle(e).backgroundColor,"
        "       said: e.textContent, over: Math.round(e.getBoundingClientRect().height)})")
    assert open_["seen"] == "visible"
    # It carries on from the face rather than repeating it.
    assert "one calamity a chapter" in open_["said"]
    assert "best of all possible worlds" not in open_["said"]
    assert open_["over"] > 40
    # Opaque, or the card underneath reads straight through it — every other
    # surface on this page is deliberately translucent.
    assert "rgba" not in open_["paint"], open_["paint"]
    assert where() == shut, "the shelf moved under the pointer"
    # A book somebody looked up carries no summary, and its card stays shut
    # rather than opening on an empty panel.
    assert page.locator(".card[data-slug='80days'] .brief").count() == 0


# ---- waiting -------------------------------------------------------------
# Every one of these was silent until a reader complained the page had frozen,
# and two of them were silent by accident rather than by omission: the wait was
# drawn and then painted over by the repaint on the next line. The stub answers
# within the frame that asked, so `hold` puts a real engine's pause back — with
# no pause there is no wait to look at.

def test_a_page_being_translated_says_so_where_the_button_stood(page):
    """The wait used to be drawn by `takeSample` and destroyed by the
    `refreshBuild` on its own last line, so what a reader saw after pressing was
    the invitation again with a faded button — the frozen page itself."""
    to_settings(page, body=scenario(hold=700))
    page.wait_for_function("!S.busy")
    page.click(".empty .ghost")
    page.wait_for_selector(".empty .ghost.busy")
    assert "Translating a page into English" in text(page, ".empty")
    assert text(page, ".empty .ghost.busy") == "Translating…"
    assert "fraction of a cent" not in text(page, ".empty")
    # And the rule under it is running, not merely present.
    assert page.eval_on_selector(
        ".empty .ghost.busy", "e => getComputedStyle(e, '::after').animationName") == "sweep"
    page.wait_for_selector("#proof-l p")
    assert page.locator(".empty").count() == 0


def test_a_further_page_supersedes_the_one_already_read(page):
    """Not the page under it left standing with a live 'Another page' beside it:
    a control that no longer answers is the frozen feeling in miniature."""
    to_settings(page, body=scenario(hold=700))
    page.wait_for_function("!S.busy")
    page.click(".empty .ghost")
    page.wait_for_selector("#proof-l p")
    page.wait_for_function("!S.busy")
    page.click("#proof-note button")
    page.wait_for_selector(".empty .ghost.busy")
    assert text(page, "#proof-note") == ""
    assert text(page, "#proof-l") == ""


def test_the_price_says_it_is_counting_rather_than_showing_an_ellipsis(page):
    to_settings(page, body=scenario(hold=700))
    page.wait_for_selector("#fig-wait:not([hidden])")
    assert "Counting the book" in text(page, "#fig-detail")
    page.wait_for_function("document.getElementById('fig').textContent.indexOf('$') !== -1")
    assert hidden(page, "#fig-wait")


def test_the_bar_sweeps_until_there_is_something_to_count(page):
    """A book is opened, and on a long PDF that is a minute before the first
    count arrives. The bar used to stand at the 4% that meant 'started'."""
    to_settings(page, body=scenario(hold=700))
    page.wait_for_function("!S.busy")
    page.click("#build")
    page.wait_for_selector(".meter .track.wait")
    assert page.eval_on_selector(
        "#bar", "e => getComputedStyle(e).animationName") == "sweep"
    page.wait_for_selector("#s-done:not([hidden])", timeout=15000)
    assert page.locator(".meter .track.wait").count() == 0


def test_a_file_being_read_says_so_on_the_card_it_was_dropped_on(page):
    upload(page, "#f-orig", "livre.txt", scenario(hold=700))
    page.wait_for_selector("#pick-orig.busy")
    assert "Reading…" in text(page, "#orig-about")
    page.wait_for_function("!document.getElementById('pick-orig').classList.contains('busy')")
    assert "Voltaire · fr · 34 ¶" == text(page, "#orig-about")


def test_the_search_says_it_is_looking_while_it_looks(page):
    """Same fault as the sample page: `paintLookup` ran before `send` set the
    busy flag, so the screen drew itself idle and never repainted."""
    # The scenario is the whole query — the stub parses the rest of the line as
    # JSON — and a query matching no fixture returns the default two works.
    look_up(page, 'SCENARIO:{"hold":700}')
    page.wait_for_selector("#look-go.busy")
    assert text(page, "#look-go") == "Looking…"
    assert "Looking on Wikisource" in text(page, "#look-out")
    page.wait_for_selector(".hit .solid")
    assert text(page, "#look-go") == "Search"


# ---- a photograph of a book ----------------------------------------------
# The measure existed and reached the terminal only, so the browser took a scan
# without a word and a reader paid to align OCR.

SCAN = {"title": "Nausea", "author": "Jean-Paul Sartre", "language": "en",
        "pages": 253, "paragraphs": 1313, "chars": 413707, "scanned": True}
CLEAN = {"title": None, "author": None, "language": "fr", "pages": 233,
         "paragraphs": 1518, "chars": 442040, "scanned": False}


def test_a_scanned_file_says_so_before_the_price(page):
    to_settings(page, route="align", body=scenario(inspect={"orig": CLEAN, "pub": SCAN}))
    page.wait_for_function("!document.getElementById('scan-note').hidden")
    note = text(page, "#scan-note")
    assert "The translation you brought is a photograph of a book" in note
    assert "words run together" in note
    # And it is above the money, not under it.
    assert page.eval_on_selector(
        "#scan-note", "n => n.compareDocumentPosition(document.getElementById('fig'))"
        " & Node.DOCUMENT_POSITION_FOLLOWING") > 0


def test_both_files_scanned_is_said_once(page):
    to_settings(page, route="align", body=scenario(inspect={"orig": SCAN, "pub": SCAN}))
    page.wait_for_function("!document.getElementById('scan-note').hidden")
    assert text(page, "#scan-note").startswith("Both files are a photograph of a book")


def test_a_clean_file_is_told_nothing_about_scans(page):
    to_settings(page, route="align", body=scenario(inspect={"orig": CLEAN, "pub": CLEAN}))
    page.wait_for_timeout(150)
    assert hidden(page, "#scan-note")


def test_the_card_names_the_scan_among_the_file_s_own_facts(page):
    upload(page, "#f-orig", "livre.txt", scenario(inspect={"orig": SCAN}))
    page.wait_for_function(
        "document.getElementById('orig-about').textContent.indexOf('Reading') === -1")
    about = text(page, "#orig-about")
    assert "scanned" in about and "1,313 ¶" in about
