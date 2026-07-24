"""Reading a chapter's number, however an edition chooses to write it.

Editions number their chapters in whatever style they please: the French says
"CHAPITRE premier" where its English translation says "CHAPTER I", and a third
edition simply writes "1". Both alignment (pairing chapters across editions) and
cleanup (finding chapters at all) need the same integer out of any of these, so
the reading lives here rather than in either.
"""
from __future__ import annotations

import re

ROMAN_RE = re.compile(r"^[ivxlcdm]+$")
ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

# Words are looked up before roman numerals on purpose — "dix" is French for ten
# and also a well-formed roman numeral for 509.
NUMBER_WORDS = {
    "premier": 1, "première": 1, "premiere": 1, "un": 1, "first": 1,
    "second": 2, "seconde": 2, "deuxième": 2, "deuxieme": 2, "deux": 2,
    "troisième": 3, "troisieme": 3, "trois": 3, "third": 3,
    "quatrième": 4, "quatrieme": 4, "quatre": 4, "fourth": 4,
    "cinquième": 5, "cinquieme": 5, "cinq": 5, "fifth": 5,
    "sixième": 6, "sixieme": 6, "six": 6, "sixth": 6,
    "septième": 7, "septieme": 7, "sept": 7, "seventh": 7,
    "huitième": 8, "huitieme": 8, "huit": 8, "eighth": 8,
    "neuvième": 9, "neuvieme": 9, "neuf": 9, "ninth": 9,
    "dixième": 10, "dixieme": 10, "dix": 10, "tenth": 10,
    "onzième": 11, "onzieme": 11, "onze": 11, "eleventh": 11,
    "douzième": 12, "douzieme": 12, "douze": 12, "twelfth": 12,
    "treizième": 13, "treizieme": 13, "treize": 13, "thirteenth": 13,
    "quatorzième": 14, "quatorzieme": 14, "quatorze": 14, "fourteenth": 14,
    "quinzième": 15, "quinzieme": 15, "quinze": 15, "fifteenth": 15,
    "seizième": 16, "seizieme": 16, "seize": 16, "sixteenth": 16,
    "dix-septième": 17, "dix-septieme": 17, "seventeenth": 17,
    "dix-huitième": 18, "dix-huitieme": 18, "eighteenth": 18,
    "dix-neuvième": 19, "dix-neuvieme": 19, "nineteenth": 19,
    "vingtième": 20, "vingtieme": 20, "vingt": 20, "twentieth": 20,
}


def _roman(token: str) -> int | None:
    total = highest = 0
    for char in reversed(token):
        value = ROMAN_VALUES[char]
        total += -value if value < highest else value
        highest = max(highest, value)
    return total or None


def chapter_number(token: str | None) -> int | None:
    """A chapter's number as an integer, whatever names it: "IV", "4",
    "quatrième", "fourth".

    None when the token is not a number at all. That case is load-bearing: a
    table of contents header ("CHAPTER PAGE") matches the heading pattern too,
    and must not be counted as a chapter.
    """
    if not token:
        return None
    word = token.strip().rstrip(".").lower()
    if word.isdigit():
        return int(word) or None
    if word in NUMBER_WORDS:
        return NUMBER_WORDS[word]
    if ROMAN_RE.match(word):
        return _roman(word)
    return None
