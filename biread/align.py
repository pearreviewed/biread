"""Align a published English translation to the French, for side-by-side reading.

Published translations do not preserve paragraph boundaries — a translator
splits a paragraph of dialogue into several, or merges two — and a published
edition carries matter the source does not: a title page, a transcriber's note,
footnotes set as their own paragraphs. So neither an index-for-index pairing nor
a proportional one survives contact with a real book.

What does work is using the generated translation as a pivot. It is aligned to
the French exactly, by construction, so aligning published English against
English is a text-similarity problem rather than a guess. Each published
paragraph is matched to the generated paragraph it most resembles, in order,
and anything resembling nothing (front matter, footnotes) is dropped.

Without a generated translation to pivot on, this falls back to distributing
proportionally within each chapter, which is only a rough approximation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cleanup import Chapter
from .errors import AlignmentError
from .translate import hash_text

# Digits included on purpose: dates, editions and quantities are among the
# most discriminating tokens a paragraph has.
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
# A published edition sets its notes as ordinary paragraphs; the source has no
# counterpart for them, so they are apparatus and never a translation of anything.
FOOTNOTE_RE = re.compile(r"^\[\d+\]")
MIN_SIMILARITY = 0.34  # a third of the shorter text must be shared to count
MIN_SHARED_WORDS = 2   # one word in common is coincidence, not correspondence

# Words too common to say anything about which paragraph a text belongs to.
STOPWORDS = frozenset("""
a an and are as at be been but by for from had has have he her his i in is it
its of on or she that the their them there they this to was were which who with
you your not no all one two more very had do did if then than when what
""".split())


@dataclass
class AlignmentReport:
    method: str  # "pivot" | "proportional"
    chapters_matched: bool
    exact: int = 0
    grouped: int = 0
    dropped: int = 0  # published paragraphs matching nothing (notes, front matter)
    unmatched: int = 0  # French paragraphs left without published text
    notes: list[str] = field(default_factory=list)

    @property
    def approximate(self) -> bool:
        # Matching against the translation is trustworthy; so is a positional
        # pass where the chapters agreed and every count lined up exactly.
        if self.method == "pivot":
            return False
        return self.grouped > 0 or not self.chapters_matched


def tokenize(text: str) -> set[str]:
    return {w for w in TOKEN_RE.findall(text.lower()) if w not in STOPWORDS and len(w) > 2}


def similarity(a: set[str], b: set[str]) -> float:
    """How much of the shorter text is contained in the longer one.

    Not an overlap coefficient like Dice: a translator routinely splits one long
    paragraph into a dozen short lines of dialogue, so the published fragment is
    a fraction of the French paragraph by construction. Dice reads that size
    asymmetry as dissimilarity — a six-word line inside a two-hundred-word
    paragraph scores about 0.05 even when every word of it matches — and the
    dialogue gets thrown away as unmatchable.
    """
    if not a or not b:
        return 0.0
    shared = len(a & b)
    if shared < MIN_SHARED_WORDS:
        return 0.0  # a single word in common is coincidence
    return shared / min(len(a), len(b))


def _distribute(french: list[str], published: list[str]) -> list[str]:
    """Proportional fallback: one published string per French paragraph."""
    f, p = len(french), len(published)
    if f == p:
        return list(published)
    out = []
    for i in range(f):
        lo = min(i * p // f, p - 1)
        hi = min(max(lo + 1, (i + 1) * p // f), p)
        out.append(" ".join(published[lo:hi]))
    return out


def _pivot(english: list[str], published: list[str]) -> tuple[list[str], int]:
    """Assign each published paragraph to the English paragraph it resembles.

    Order is preserved on both sides, so this is a monotonic many-to-one
    matching, solved with the usual dynamic program. A published paragraph
    whose best match is still weak is dropped rather than forced somewhere it
    does not belong. Returns (one string per English paragraph, dropped count).
    """
    n, m = len(english), len(published)
    if not n or not m:
        return [""] * n, m

    en_tokens = [tokenize(t) for t in english]
    pub_tokens = [tokenize(t) for t in published]
    # score[i][j]: what published i is worth against English j, or dropping it.
    score = [
        [max(similarity(pub_tokens[i], en_tokens[j]), MIN_SIMILARITY) for j in range(n)]
        for i in range(m)
    ]

    NEG = float("-inf")
    # best[i][j]: best total for the first i published against the first j English.
    best = [[NEG] * (n + 1) for _ in range(m + 1)]
    best[0] = [0.0] * (n + 1)
    for i in range(1, m + 1):
        row, previous = best[i], best[i - 1]
        for j in range(1, n + 1):
            stay = previous[j] + score[i - 1][j - 1]  # published i belongs to English j
            advance = row[j - 1]  # English j takes nothing more
            row[j] = stay if stay > advance else advance

    # Walk it back to recover which published paragraphs went where.
    groups: list[list[str]] = [[] for _ in range(n)]
    dropped = 0
    i, j = m, n
    while i > 0 and j > 0:
        if best[i][j] == best[i][j - 1]:
            j -= 1
            continue
        if similarity(pub_tokens[i - 1], en_tokens[j - 1]) < MIN_SIMILARITY:
            dropped += 1
        else:
            groups[j - 1].append(published[i - 1])
        i -= 1
    dropped += i  # anything left over never found a home

    return [" ".join(reversed(g)) for g in groups], dropped


ROMAN_RE = re.compile(r"^[ivxlcdm]+$")
ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}

# Editions number their chapters in whatever style they please: the French says
# "CHAPITRE premier" where its English translation says "CHAPTER I". Both have to
# reduce to the same integer before the two books can be matched on it. Words are
# looked up before roman numerals on purpose — "dix" is French for ten and also a
# well-formed roman numeral for 509.
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


def trim_matter(chapters: list[Chapter]) -> list[Chapter]:
    """Drop what brackets a book without being the book: a title page, a table of
    contents, a publisher's notice or a critic's introduction in front; a licence
    or endnotes behind. These are exactly the sections cleanup could not number.

    Leaving them in is what puts two editions permanently out of step — one
    edition's forty-page introduction would otherwise shift every paragraph after
    it. A book with no numbered chapters is returned untouched: there is nothing
    to anchor on, and all of it may be the text.
    """
    numbered = [i for i, c in enumerate(chapters) if chapter_number(c.number) is not None]
    if not numbered:
        return chapters
    return chapters[numbered[0] : numbered[-1] + 1]


def _pair_by_number(french: list[Chapter], published: list[Chapter]):
    """Pair chapters on the number they carry rather than the order they arrive
    in, so an extra preface on one side cannot shift the book. A French chapter
    with no counterpart pairs with None and is left blank rather than guessed."""
    by_number: dict[int, Chapter] = {}
    for chapter in published:
        number = chapter_number(chapter.number)
        if number is not None and number not in by_number:
            by_number[number] = chapter
    return [(c, by_number.get(chapter_number(c.number))) for c in french]


def _label(chapter: Chapter, index: int) -> str:
    if chapter.number:
        return f"Chapitre {chapter.number}"
    return "Opening section" if index == 0 else f"Section {index + 1}"


def align_published(
    french: list[Chapter],
    published: list[Chapter],
    translations: dict[str, str] | None = None,
) -> tuple[dict[str, str], AlignmentReport]:
    """Map French paragraph hash -> published English text.

    Pass `translations` (French hash -> generated English) to align by
    similarity, which is what makes the result trustworthy.
    """
    fr_bodies = [c for c in trim_matter(french) if c.paragraphs]
    pub_bodies = [c for c in trim_matter(published) if c.paragraphs]

    if not fr_bodies:
        raise AlignmentError("the French text has no paragraphs to align against.")
    if not pub_bodies:
        raise AlignmentError("the published translation has no paragraphs.")

    # Chapters are the one boundary translators keep, and the number a chapter
    # carries survives translation even when none of its words do. Pair on that
    # number rather than on position: an extra preface on one side then cannot
    # shift the book, and drift stays inside a single chapter.
    fr_numbers = {chapter_number(c.number) for c in fr_bodies} - {None}
    pub_numbers = {chapter_number(c.number) for c in pub_bodies} - {None}
    by_number = len(fr_numbers & pub_numbers) >= 2  # one match could be coincidence

    matched = by_number or len(fr_bodies) == len(pub_bodies)
    use_pivot = bool(translations)
    report = AlignmentReport(
        method="pivot" if use_pivot else "proportional", chapters_matched=matched
    )
    aligned: dict[str, str] = {}

    if by_number:
        pairs = _pair_by_number(fr_bodies, pub_bodies)
    elif len(fr_bodies) == len(pub_bodies):
        pairs = list(zip(fr_bodies, pub_bodies))
    else:
        pairs = [(
            Chapter(None, None, [p for c in fr_bodies for p in c.paragraphs]),
            Chapter(None, None, [p for c in pub_bodies for p in c.paragraphs]),
        )]
        report.notes.append(
            f"Chapter structures differ ({len(fr_bodies)} French vs {len(pub_bodies)} "
            f"published) and share no chapter numbers, so the book was aligned as one "
            f"run rather than chapter by chapter."
        )

    for index, (fr, pub) in enumerate(pairs):
        if pub is None:
            report.unmatched += len(fr.paragraphs)
            report.notes.append(
                f"{_label(fr, index)}: the published edition has no chapter of that "
                f"number, so it is left blank rather than filled with a guess."
            )
            for paragraph in fr.paragraphs:
                aligned[hash_text(paragraph)] = ""
            continue
        if use_pivot:
            english = [translations.get(hash_text(p), "") for p in fr.paragraphs]
            prose = [p for p in pub.paragraphs if not FOOTNOTE_RE.match(p)]
            report.dropped += len(pub.paragraphs) - len(prose)
            texts, dropped = _pivot(english, prose)
            report.dropped += dropped
            empty = sum(1 for t in texts if not t)
            report.unmatched += empty
            if dropped or empty:
                detail = []
                if dropped:
                    detail.append(f"{dropped} published paragraph(s) set aside as notes or front matter")
                if empty:
                    detail.append(f"{empty} French paragraph(s) found no counterpart")
                report.notes.append(f"{_label(fr, index)}: " + "; ".join(detail) + ".")
            report.exact += 1
        else:
            texts = _distribute(fr.paragraphs, pub.paragraphs)
            if len(fr.paragraphs) == len(pub.paragraphs):
                report.exact += 1
            else:
                report.grouped += 1
                report.notes.append(
                    f"{_label(fr, index)}: {len(fr.paragraphs)} French paragraph(s) ↔ "
                    f"{len(pub.paragraphs)} published — grouped proportionally."
                )
        for paragraph, text in zip(fr.paragraphs, texts):
            aligned[hash_text(paragraph)] = text

    return aligned, report
