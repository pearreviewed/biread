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
    # Cardinals, not only ordinals: an edition may head its chapters "One",
    # "Two", "Twenty-one" as readily as "First" — Eleanor Marx's Madame Bovary
    # does — and the table that reads a spelled-out quantity in prose reads
    # these too. Before the roman check, which would take "mi" for 1001.
    cardinal = _cardinal_value(_NUMBER_WORD_RE.findall(word))
    if cardinal:
        return cardinal
    if ROMAN_RE.match(word):
        return _roman(word)
    return None


# Cardinal number words, French and English in one table, for reading a spelled-out
# quantity in prose back to its value — so "seventy-one" and "soixante et onze"
# both anchor on 71, the way the digits "1755" already do. A word meaning different
# numbers in each language would be a hazard, but there is none in common here; and
# a coincidental small number ("three"/"trois") is filtered by the anchoring, which
# only trusts a value the two editions use the same, sparing number of times.
_CARDINALS = {
    "zero": 0, "zéro": 0,
    "un": 1, "une": 1, "one": 1, "deux": 2, "two": 2, "trois": 3, "three": 3,
    "quatre": 4, "four": 4, "cinq": 5, "five": 5, "six": 6, "sept": 7, "seven": 7,
    "huit": 8, "eight": 8, "neuf": 9, "nine": 9,
    "dix": 10, "ten": 10, "onze": 11, "eleven": 11, "douze": 12, "twelve": 12,
    "treize": 13, "thirteen": 13, "quatorze": 14, "fourteen": 14, "quinze": 15,
    "fifteen": 15, "seize": 16, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
    "vingt": 20, "vingts": 20, "twenty": 20, "trente": 30, "thirty": 30,
    "quarante": 40, "forty": 40, "cinquante": 50, "fifty": 50, "soixante": 60,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "cent": 100, "cents": 100, "hundred": 100, "mille": 1000, "thousand": 1000,
    "million": 1_000_000, "millions": 1_000_000,
}
#: Joins two number words without being one — "soixante *et* onze", "three hundred
#: *and* fifty" — so a run reads through it.
_NUMBER_CONNECTORS = {"et", "and"}
_NUMBER_WORD_RE = re.compile(r"[a-zàâäçéèêëîïôùûœ]+")


def _cardinal_value(words: list[str]) -> int | None:
    """The integer a run of cardinal words spells, or None if it spells nothing.

    Additive within the low hundreds, multiplicative across a scale ("trois cent"
    = 300, "deux mille" = 2000). French "quatre-vingt(s)" — four twenties, not four
    then twenty — is the one place the addition breaks, and is read specially."""
    total = current = 0
    index = 0
    while index < len(words):
        word = words[index]
        if word == "quatre" and index + 1 < len(words) and words[index + 1] in ("vingt", "vingts"):
            current += 80
            index += 2
            continue
        value = _CARDINALS.get(word)
        if value is None:
            return None
        if value == 100:
            current = (current or 1) * 100
        elif value >= 1000:
            total += (current or 1) * value
            current = 0
        else:
            current += value
        index += 1
    return total + current


def number_tokens(text: str) -> set[str]:
    """A "num<value>" token for every spelled-out number in the text, so a quantity
    anchors across two editions like a name does: "num71" from both "seventy-one"
    and "soixante et onze". Digits are already caught as tokens elsewhere."""
    tokens: set[str] = set()
    run: list[str] = []
    for word in _NUMBER_WORD_RE.findall(text.lower().replace("-", " ")) + [""]:
        if word in _CARDINALS:
            run.append(word)
        elif run and word in _NUMBER_CONNECTORS:
            continue  # a connector holds the run open without adding to it
        elif run:
            value = _cardinal_value(run)
            if value:
                tokens.add(f"num{value}")
            run = []
    return tokens
