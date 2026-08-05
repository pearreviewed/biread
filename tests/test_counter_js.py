"""The page counter's number, lifted out of the shipped reader.

A book over 999 spreads read "1 / 1076" in a box measured for "12 / 38", so the
total was clipped and looked as though it stopped at 999. Building a
thousand-spread book to test that would take a novel; the formatting is lifted
from reader.js instead, the way the gloss pipeline is, so what runs here is what
ships.
"""
from __future__ import annotations

import pytest

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed"
).sync_playwright

from biread.render import TEMPLATES  # noqa: E402


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture(scope="module")
def short_total(browser):
    source = (TEMPLATES / "reader.js").read_text(encoding="utf-8")
    start = source.index("  function shortTotal(")
    end = source.index("  var counterWidthFor")
    page = browser.new_page()
    page.set_content("<html><body></body></html>")
    page.evaluate(
        "(code) => { window.run = new Function(code + '; return shortTotal;')(); }",
        source[start:end],
    )
    yield lambda n: page.evaluate("(n) => run(n)", n)
    page.close()


@pytest.mark.parametrize("total,shown", [
    (1, "1"),
    (38, "38"),
    (236, "236"),        # Candide
    (818, "818"),        # Bovary
    (999, "999"),        # the last exact one
    (1000, "1k"),        # not "1.0k"
    (1076, "1.1k"),      # 20,000 Leagues
    (1500, "1.5k"),
    (12345, "12.3k"),
])
def test_a_long_book_says_how_long_without_growing_the_header(short_total, total, shown):
    assert short_total(total) == shown


def test_every_book_on_the_shelf_today_still_reads_exactly(short_total):
    """Abbreviation must not reach the books people are actually reading."""
    for spreads in (44, 236, 518, 818):
        assert "k" not in short_total(spreads)


@pytest.fixture(scope="module")
def fit_counter(browser):
    """`fitCounter` from the shipped reader, over a real counter element."""
    source = (TEMPLATES / "reader.js").read_text(encoding="utf-8")
    start = source.index("  function shortTotal(")
    end = source.index("  function updateCounter(")
    # A button, as the reader has it, and with the stylesheet's own rule: a block
    # element measures its container rather than its text, and would have made
    # every width equal — which is to say, would have passed either way.
    css = (TEMPLATES / "reader.css").read_text(encoding="utf-8")
    rule = css[css.index(".counter, .counter-input {"):]
    rule = rule[:rule.index("\n")]
    page = browser.new_page()
    page.set_content(
        f"<html><head><style>{rule}</style></head><body>"
        "<button id='counter' class='counter'></button>"
        "<input id='counter-input' class='counter-input'></body></html>")
    page.evaluate(
        "(code) => { window.fit = new Function(code + '; return fitCounter;')(); }",
        source[start:end])

    def run(total):
        page.evaluate("(n) => fit(document.getElementById('counter'), n)", total)
        return page.evaluate(
            "() => parseFloat(document.getElementById('counter').style.width)")

    yield run
    page.close()


def test_the_counter_box_never_narrows_again(fit_counter):
    """A width that tracks the total exactly is a width that keeps changing, and
    on a window where the header is near wrapping that is a feedback loop: the
    counter widens, the header takes a second line, the stage loses 50px,
    pagination restarts, the total falls back to double figures, the counter
    narrows, the header unwraps. At 1440px wide 20,000 Leagues never finished
    opening — the header flipped between 72px and 122px indefinitely.
    """
    wide = fit_counter(1074)
    assert fit_counter(41) == wide, "narrowed when pagination restarted"
    assert fit_counter(266) == wide
    assert fit_counter(3404) >= wide, "must still grow for a longer book"


def test_the_counter_also_carries_the_number_it_abbreviates():
    """The label is for the reader; anything reading the page wants the number.

    The publication check parsed the label, so the first book long enough to be
    abbreviated — 20,000 Leagues, at 1,076 spreads — stopped it dead with
    int(' 1.1k'). Asserted against the shipped source rather than a rendering,
    for the same reason the rest of this file is.
    """
    source = (TEMPLATES / "reader.js").read_text(encoding="utf-8")
    body = source[source.index("  function updateCounter("):]
    body = body[:body.index("\n  }")]
    assert "el.dataset.total = spreads.length;" in body
