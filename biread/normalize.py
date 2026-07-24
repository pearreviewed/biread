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


def repair(raw: str) -> tuple[str, list[Removal]]:
    """Raw extractor text -> (repaired text, what was repaired)."""
    removed: list[Removal] = []

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

    return "\n".join(lines), removed
