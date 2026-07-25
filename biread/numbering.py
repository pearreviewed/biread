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
    "premier": 1, "première": 1, "premiere": 1, "un": 1, "unième": 1, "unieme": 1, "first": 1,
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
    "trentième": 30, "trentieme": 30, "trente": 30, "thirtieth": 30,
    "quarantième": 40, "quarantieme": 40, "quarante": 40, "fortieth": 40,
    "cinquantième": 50, "cinquantieme": 50, "cinquante": 50, "fiftieth": 50,
}

# The tens a compound ordinal builds on: "vingt-neuvième" is twenty-plus-nine.
TENS = {"vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60}


def _compound_ordinal(word: str) -> int | None:
    """A hyphenated French ordinal read by summing its parts: "dix-septième" is
    ten-plus-seven, "vingt-neuvième" twenty-plus-nine, "trente et unième"
    thirty-plus-one. Additive only — the irregular "quatre-vingt" (eighty, not
    four-twenties) is past any book's chapter count and deliberately not read."""
    parts = [p for p in re.split(r"[-\s]+", word) if p and p != "et"]
    if len(parts) < 2:
        return None
    total = 0
    for part in parts:
        value = TENS.get(part) or NUMBER_WORDS.get(part)
        if value is None:
            return None
        total += value
    return total or None


#: (value, symbol), largest first, for writing an integer as a roman numeral.
_ROMAN_NUMERALS = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)


def to_roman(number: int) -> str:
    """An integer as a roman numeral: 17 -> "XVII". The chapter heading a reader
    sees, whichever way the edition happened to spell its number in the source."""
    out = []
    for value, symbol in _ROMAN_NUMERALS:
        count, number = divmod(number, value)
        out.append(symbol * count)
    return "".join(out)


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
    compound = _compound_ordinal(word)
    if compound is not None:
        return compound
    if ROMAN_RE.match(word):
        return _roman(word)
    return None
