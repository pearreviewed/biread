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
    page.wait_for_selector("#go-key")
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
    """The common path: through the fork and step one, arriving at step two."""
    page.click("#go-key")
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


# ---- the fork ------------------------------------------------------------

def test_the_door_asks_only_who_does_the_work(page):
    assert showing(page, "fork")
    assert text(page, ".hero h1").startswith("The original on one page")
    assert page.eval_on_selector_all(".fork > div", "n => n.length") == 2


def test_either_path_leads_to_the_book(page):
    page.click("#go-local")
    assert showing(page, "books")
    page.click("[data-goto=fork]")
    page.click("#go-key")
    assert showing(page, "books")


def test_the_local_path_asks_for_no_key(page):
    page.click("#go-local")
    upload(page, "#f-orig", "livre.txt")
    page.wait_for_function("!document.getElementById('to-settings').disabled")
    page.click("#to-settings")
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
    page.wait_for_selector("#go-key")
    assert page.eval_on_selector("html", "e => e.dataset.theme") == "night"
    page.click(".theme button[aria-label=Day]")


# ---- step one: the route and the files -----------------------------------

def test_the_second_file_is_asked_for_only_when_it_is_needed(page):
    page.click("#go-key")
    assert hidden(page, "#pick-pub")
    page.click("[data-route=align]")
    assert not hidden(page, "#pick-pub")


def test_the_aligned_route_will_not_go_on_without_the_edition(page):
    page.click("#go-key")
    page.click("[data-route=align]")
    upload(page, "#f-orig", "livre.txt")
    page.wait_for_timeout(200)
    assert page.eval_on_selector("#to-settings", "e => e.disabled")
    upload(page, "#f-pub", "edition.txt")
    page.wait_for_function("!document.getElementById('to-settings').disabled")


def test_a_file_card_shows_what_the_file_says_about_itself(page):
    page.click("#go-key")
    upload(page, "#f-orig", "livre.txt")
    page.wait_for_function(
        "document.getElementById('orig-about').textContent.indexOf('Reading') === -1")
    assert text(page, "#orig-name") == "livre.txt"
    about = text(page, "#orig-about")
    assert "Voltaire" in about and "34 ¶" in about


def test_a_file_card_stays_quiet_about_what_it_cannot_read(page):
    page.click("#go-key")
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
    page.click("#go-key")
    upload(page, "#f-orig", "livre.txt",
           scenario(failOn="inspect", error="livre.txt is not a readable EPUB"))
    page.wait_for_function("!document.getElementById('books-alert').hidden")
    assert "not a readable EPUB" in text(page, "#books-alert")


# ---- shape ---------------------------------------------------------------

@pytest.mark.parametrize("screen", ["fork", "books", "settings", "binding", "done"])
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
