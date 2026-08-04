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
def short_total():
    source = (TEMPLATES / "reader.js").read_text(encoding="utf-8")
    start = source.index("  function shortTotal(")
    end = source.index("  var counterWidthFor")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content("<html><body></body></html>")
        page.evaluate(
            "(code) => { window.run = new Function(code + '; return shortTotal;')(); }",
            source[start:end],
        )
        yield lambda n: page.evaluate("(n) => run(n)", n)
        browser.close()


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
