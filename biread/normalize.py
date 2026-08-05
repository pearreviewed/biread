"""Undo the standard injuries a PDF extractor inflicts, before cleanup reads it.

Cleanup and everything after it assume text that reads like a book: paragraphs
separated by blank lines, words kept whole, headings intact. A PDF does not
arrive that way. It arrives with a running page marker stamped into the middle
of sentences ("…the Abares. [Pg 9] The King…"), words broken across a line by a
hyphen, and — the failure that motivated this module — a chapter's heading word
severed from the numeral that names it, each marooned on its own line amid the
whitespace of a centred title.

This layer repairs those before any downstream stage tries to make sense of the
text, and reports each repair so a source that gets damaged in some new way
shows up in the run's output rather than silently misreading.
"""
from __future__ import annotations

import re

from .cleanup import Removal
from .numbering import chapter_number

# "[Pg 9]", "[Pg xviii]", "[Page 12]" — Project Gutenberg's page-boundary stamp.
# It lands both on its own line and inside a sentence, so it is cut as a token
# wherever it sits rather than as a whole line.
PAGE_MARKER_RE = re.compile(r"\[\s*(?:pg|page)\.?\s*[ivxlcdm\d]+\s*\]", re.IGNORECASE)

# Typographic ligatures, which a PDF's font carries as single glyphs and pypdf
# hands back verbatim: "ﬁnd", "ﬂurried". They read almost normally and are almost
# nothing else — search, copy-and-paste and every word-level stage see a
# character no keyboard makes. Always safe to expand: the codepoint is a shape,
# never a meaning, so this needs no format gate.
LIGATURES = str.maketrans({
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
})

# A word broken across a line break: a letter, a hyphen, end of line. Joined
# only when the next line resumes in lower case — an upper-case continuation is
# more likely a real compound (a proper noun) split at its own hyphen.
LINE_BREAK_HYPHEN_RE = re.compile(r"(\w)-$")

# A heading word standing alone on its line, its numeral stranded below it.
HEADING_WORD_RE = re.compile(r"(?:chapitre|chapter)", re.IGNORECASE)


def _rejoin_split_headings(lines: list[str]) -> tuple[list[str], int]:
    """Pull a numeral back up onto the heading word it belongs to.

    pypdf lays a centred "CHAPTER / I" out as two lines with the numeral adrift;
    left apart, the heading pattern matches neither half and the chapter is lost.
    Only a numeral within the next couple of lines is pulled up, so a "CHAPTER"
    that is genuinely a word in a sentence is left alone.
    """
    out: list[str] = []
    joined = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if HEADING_WORD_RE.fullmatch(line.strip().rstrip(".")):
            look = i + 1
            while look < len(lines) and look <= i + 2 and not lines[look].strip():
                look += 1
            if look < len(lines) and chapter_number(lines[look].strip()) is not None:
                out.append(f"{line.strip()} {lines[look].strip()}")
                i = look + 1
                joined += 1
                continue
        out.append(line)
        i += 1
    return out, joined


def _dehyphenate(lines: list[str]) -> tuple[list[str], int]:
    out: list[str] = []
    healed = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if LINE_BREAK_HYPHEN_RE.search(line.rstrip()) and nxt[:1].islower():
            head, _, tail = nxt.strip().partition(" ")
            out.append(line.rstrip()[:-1] + head)
            lines[i + 1] = tail
            healed += 1
        else:
            out.append(line)
        i += 1
    return out, healed


#: How far below the page's measure a line must fall to have ended its paragraph
#: rather than merely run out of room. Judged against the 90th-percentile line
#: length, which is the measure the page was set to.
SHORT_LINE = 0.8

SENTENCE_END_RE = re.compile(r"[.!?…][\"”»’']?$")
SENTENCE_START_RE = re.compile(r"[\"“«‘(]?[A-ZÀ-Þ]")


def _measure(lines: list[str]) -> int:
    lengths = sorted(len(line.strip()) for line in lines if line.strip())
    return lengths[int(len(lengths) * 0.9)] if lengths else 0


#: A file whose blank-line blocks run longer than a page of prose never separated
#: its paragraphs at all. Whatever its format, that information was lost before it
#: reached us — see `_never_broke`.
UNBROKEN_BLOCK = 2000


def _never_broke(text: str) -> bool:
    """Did this file separate its paragraphs at all?

    The repair below is safe on a PDF because a PDF has no way to say whether it
    means the blank lines it omits. Every other format does mean it, which is why
    the repair is not simply run on all of them — an EPUB that puts one blank line
    where a printer put an indent is describing its own house style.

    But a file arriving in blocks the length of a chapter is not describing
    anything: nothing sets its prose in blocks of two thousand characters. That is
    a conversion that dropped the marks — a PDF flattened into Word loses every
    one of them — and the repair is a rescue rather than a guess.
    """
    blocks = [b for b in re.split(r"\n\s*\n+", text.strip()) if b.strip()]
    if not blocks:
        return False
    lengths = sorted(len(b) for b in blocks)
    return lengths[len(lengths) // 2] > UNBROKEN_BLOCK


def _unfuse_paragraphs(lines: list[str]) -> tuple[list[str], int]:
    """Put back the blank lines a PDF never had.

    A page is set to a measure — one fixed column width — so a line stopping well
    short of it stopped because its paragraph ended, not because it ran out of
    room. Where such a line also closes a sentence and the next one opens a
    sentence, they belong to different paragraphs, and a blank line goes between.

    Without this, a run of dialogue arrives as a single block: Candide's published
    edition came out as 120 paragraphs, one of them four pages long, against the
    French's 630 — and nothing can be aligned against that.

    Run on every PDF, and on any other format only where the file never came
    apart at all (`_never_broke`) — a text or EPUB that omits the odd blank line
    is saying something about itself, and one that omits all of them has lost
    them.
    """
    measure = _measure(lines)
    if not measure:
        return lines, 0
    out: list[str] = []
    split = 0
    for i, line in enumerate(lines):
        out.append(line)
        text = line.strip()
        following = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if not text or not following:
            continue
        if (len(text) < measure * SHORT_LINE
                and SENTENCE_END_RE.search(text)
                and SENTENCE_START_RE.match(following)):
            out.append("")
            split += 1
    return out, split


def repair(raw: str, from_pdf: bool = False) -> tuple[str, list[Removal]]:
    """Raw extractor text -> (repaired text, what was repaired).

    `from_pdf` admits the repairs that only a PDF always needs; a file of any
    format that never came apart into paragraphs gets them too — see
    `_unfuse_paragraphs` and `_never_broke`.
    """
    removed: list[Removal] = []

    expanded = sum(raw.count(glyph) for glyph in "ﬀﬁﬂﬃﬄﬅﬆ")
    if expanded:
        raw = raw.translate(LIGATURES)
        removed.append(Removal("Ligature expanded", f"{expanded} glyph(s), e.g. “ﬁ” to “fi”"))

    first = PAGE_MARKER_RE.search(raw)
    text, marks = PAGE_MARKER_RE.subn(" ", raw)
    if marks:
        removed.append(Removal("Page marker", f"{marks} removed, e.g. “{first.group().strip()}”"))

    lines = text.split("\n")
    lines, joined = _rejoin_split_headings(lines)
    if joined:
        removed.append(Removal("Split heading rejoined", f"{joined} heading(s) reunited with their numeral"))

    lines, healed = _dehyphenate(lines)
    if healed:
        removed.append(Removal("Line-broken word rejoined", f"{healed} hyphenated word(s) made whole"))

    if from_pdf or _never_broke(text):
        lines, split = _unfuse_paragraphs(lines)
        if split:
            removed.append(Removal(
                "Paragraph break restored", f"{split} run-together paragraph(s) separated"
            ))

    return "\n".join(lines), removed
