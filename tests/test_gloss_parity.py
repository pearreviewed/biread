"""The reader's gloss pipeline against the one in Python, on the same paragraphs.

A book published without glosses is glossed by its reader, in the browser, on
the reader's own key — so the judgement in `biread/gloss.py` is necessarily
written a second time in `reader.js`. Two implementations of one rule drift, and
the drift is invisible: a unit silently kept where Python would drop it looks
like a gloss, not like a bug.

So they are run side by side here. The Python answer is the truth; the JS answer
has to match it exactly, on real French with the things that actually break
matching — curly apostrophes, elisions, guillemets, an ellipsis that folds to
three characters, an infinitive echoing its own surface, and units too wide to
hover.
"""
from __future__ import annotations

import json

import pytest

from biread.gloss import FIELD, anchor, displayable, parse_units, protocol

sync_playwright = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed"
).sync_playwright

from biread.render import TEMPLATES  # noqa: E402


def f(*fields: str) -> str:
    return FIELD.join(fields)


#: (paragraph, the model's reply). Each carries something that has broken
#: matching before, or that the width rule exists to catch.
CASES = [
    (
        "Il y avait en Vestphalie un jeune garçon.",
        "\n".join([
            f("Il y avait", "verb", "there was", "inf=avoir"),
            f("en Vestphalie", "prepositional phrase", "in Westphalia"),
            f("un jeune garçon", "noun phrase", "a young boy"),
        ]),
    ),
    (
        # Curly apostrophes on both sides of an elision; the model straightens them.
        "L’escalier de l’étoile qu’il monta.",
        "\n".join([
            f("L'escalier", "noun", "the staircase"),
            f("de l'étoile", "prepositional phrase", "of the star"),
            f("qu'il monta", "verb", "that he climbed", "inf=monter"),
        ]),
    ),
    (
        # An ellipsis: one source character folding to three, so every offset
        # after it is wrong unless the index map is walked properly.
        "Et puis… dit-il avec une petite fourmilière.",
        "\n".join([
            f("Et puis...", "adverb", "and then"),
            f("dit-il", "verb", "he said", "inf=dire"),
            f("une petite fourmilière", "noun phrase", "a little anthill"),
        ]),
    ),
    (
        # Over-broad: a noun-of-noun, a coordination, and a predicate.
        "Les citoyens de la terre virent des mites attractives et répulsives.",
        "\n".join([
            f("Les citoyens de la terre", "noun phrase", "the citizens of the earth"),
            f("virent", "verb", "saw", "inf=voir"),
            f("des mites attractives et répulsives", "noun phrase", "attractive and repulsive mites"),
        ]),
    ),
    (
        # An infinitive echoing its own surface, and a field the prompt no longer
        # asks for: both must be dropped rather than printed under the pointer.
        "Il ne savait plus parler, et il n’avait pas pu partir.",
        "\n".join([
            f("parler", "verb", "to speak", "inf=parler"),
            f("il n'avait pas pu partir", "verb", "he had not been able to leave",
              "inf=pouvoir", "pc=il n'avait pas pu"),
        ]),
    ),
    (
        # A surface the model invented: the whole paragraph must go unglossed.
        "Le procès dura.",
        "\n".join([
            f("Le procès", "noun phrase", "the trial"),
            f("se prolongea", "verb", "dragged on", "inf=prolonger"),
        ]),
    ),
]


def in_python(paragraph: str, reply: str):
    located = anchor(paragraph, parse_units(reply))
    if not located:
        return None
    return [[u.start, u.end, u.pos, u.gloss, u.infinitive]
            for u in displayable(paragraph, located)]


@pytest.fixture(scope="module")
def in_js():
    """The reader's own functions, lifted out of reader.js and run on the cases.

    The template is loaded as it ships — no copy of the algorithms lives here —
    so a change to reader.js is measured rather than mirrored.
    """
    source = (TEMPLATES / "reader.js").read_text(encoding="utf-8")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        # reader.js is one IIFE that expects the book DOM; the pipeline is lifted
        # out by running it with a GLOSS in scope and handing back the closures.
        start = source.index("var WORD_RE = /")
        end = source.index("  // ---------- revise ----------")
        page.set_content("<html><body></body></html>")
        page.evaluate(
            "([code, gloss]) => { window.GLOSS = gloss; window.run = new Function('GLOSS', "
            "code + '; return {parseUnits, anchorUnits, displayableUnits};')(gloss); }",
            [source[start:end], protocol()],
        )
        yield lambda paragraph, reply: page.evaluate(
            "([p, r]) => { const u = run.anchorUnits(p, run.parseUnits(r));"
            " return u ? run.displayableUnits(p, u) : null; }",
            [paragraph, reply],
        )
        browser.close()


@pytest.mark.parametrize("paragraph,reply", CASES, ids=[c[0][:28] for c in CASES])
def test_the_reader_reaches_the_same_units_as_python(in_js, paragraph, reply):
    expected = in_python(paragraph, reply)
    assert in_js(paragraph, reply) == expected, (
        "the reader's gloss pipeline has drifted from biread/gloss.py"
    )


def test_a_reply_that_will_not_anchor_glosses_nothing_either_way(in_js):
    paragraph, reply = CASES[-1]
    assert in_python(paragraph, reply) is None
    assert in_js(paragraph, reply) is None


def test_the_protocol_carries_what_the_reader_needs():
    """Every field the reader reads out of GLOSS, named here so removing one from
    `protocol()` fails loudly rather than silently disabling a rule."""
    js = (TEMPLATES / "reader.js").read_text(encoding="utf-8")
    got = protocol()
    for field in ("prompt", "field", "fold", "maxContentWords", "predicatePos",
                  "functionWords", "coordinators", "prepositions"):
        assert field in got, f"protocol() dropped {field}"
        assert f"GLOSS.{field}" in js, f"reader.js never reads GLOSS.{field}"
    assert json.dumps(got)  # serialisable: it travels inside the book
