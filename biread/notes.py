"""Finding a book's apparatus and taking it out of the reading text.

Editions carry notes in whatever shape their typesetter chose: "[1] From micros,
small", "(1) Voyez la préface", "¹ A note", "1. A note", a run of them closing a
chapter or the book. Left in, each becomes a paragraph of the bilingual text —
translated at cost, glossed at cost, and set opposite a paragraph of the other
edition's prose, which shifts everything after it.

Nothing here removes a paragraph on its shape alone. A paragraph opening "1." is
a note in one book and an ordinary numbered list in another, and there is no
telling them apart by looking. What tells them apart is corroboration: a note is
referred to from the prose, or it sits in the run of notes that closes a
chapter. A paragraph with neither is left where it is, because a wrongly deleted
sentence is silent and unrecoverable, where a note left in is merely untidy.

Everything taken out is reported, so a book whose apparatus is shaped in some new
way shows up in the run's output rather than quietly losing a page of prose.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

SUPERSCRIPTS = "¹²³⁴⁵⁶⁷⁸⁹"
_SUPERSCRIPT_VALUE = {ch: str(i + 1) for i, ch in enumerate(SUPERSCRIPTS)}

#: How a note's own paragraph opens, and the number it claims.
BODY_SHAPES = (
    re.compile(r"^\[(\d{1,3})\]\s+"),
    re.compile(r"^\((\d{1,3})\)\s+"),
    re.compile(rf"^([{SUPERSCRIPTS}])\s*"),
    re.compile(r"^(\d{1,3})\.\s+"),
)

#: How the prose refers to one, always attached to the word it follows — a bare
#: "[1]" on its own is a note's own marker, not a reference to it.
REFERENCE_SHAPES = (
    re.compile(r"(?<=\S)\[(\d{1,3})\]"),
    re.compile(r"(?<=\w)\((\d{1,3})\)"),
    re.compile(rf"(?<=\S)([{SUPERSCRIPTS}])"),
)

#: Two is a run, one is a sentence that happens to start with a numeral.
MIN_TRAILING_RUN = 2

#: A note's body inside a run of them, wherever the run begins — at the head of
#: the paragraph or part-way through it. Only the bracketed and parenthesised
#: shapes, and never glued to a word: "1." mid-paragraph ends one sentence and
#: starts another far more often than it opens a note, and "Micromégas[1]" is a
#: reference to a note rather than the body of one.
FUSED_SHAPE = re.compile(r"(?:^|(?<=\s))[\[(](\d{1,3})[\])]\s*[-–—]?\s+")

#: How many fused note-openings make an apparatus. Three, where a paragraph of
#: its own needs two: a break that is not there in the file is weaker evidence
#: than one that is, so it is asked for more.
MIN_FUSED_RUN = 3


def _fused(paragraph: str) -> tuple[str, list[Note]]:
    """One paragraph carrying a whole apparatus, split back into its notes.

    An edition whose notes are set close together arrives as a single block — the
    French Nausea ends on `FIN [1] - Un mot laissé en blanc. [2] - Un mot est
    raturé…`, twelve editor's notes and the novel's last word in one paragraph of
    fourteen hundred characters. Read as prose it is translated, glossed, and set
    against a page of the other edition's ending, which shifts the close of the
    book.

    The corroboration is the same one `_trailing_run` reads, looked for inside a
    paragraph instead of across several: numbers that open notes and *count* —
    1, 2, 3 — are an apparatus, because prose does not enumerate itself. Anything
    short of a counting run leaves the paragraph exactly as it was.
    """
    found = [(m.start(), m.end(), int(m.group(1))) for m in FUSED_SHAPE.finditer(paragraph)]
    run: list[tuple[int, int, int]] = []
    for mark in found:
        if run and mark[2] != run[-1][2] + 1:
            run = []
        if not run and mark[2] != 1:
            continue
        run.append(mark)
    if len(run) < MIN_FUSED_RUN:
        return paragraph, []

    notes = [
        Note(number, paragraph[start:run[at + 1][0]].strip() if at + 1 < len(run)
             else paragraph[start:].strip())
        for at, (start, _, number) in enumerate(run)
    ]
    return paragraph[:run[0][0]].strip(), notes


@dataclass(frozen=True)
class Note:
    number: int
    text: str


def _opening(paragraph: str) -> int | None:
    """The note number a paragraph claims to be, by how it opens."""
    for shape in BODY_SHAPES:
        found = shape.match(paragraph)
        if found:
            token = _SUPERSCRIPT_VALUE.get(found.group(1), found.group(1))
            return int(token)
    return None


def references(paragraphs: list[str]) -> set[int]:
    """The note numbers the prose actually points at."""
    found: set[int] = set()
    for paragraph in paragraphs:
        for shape in REFERENCE_SHAPES:
            for token in shape.findall(paragraph):
                found.add(int(_SUPERSCRIPT_VALUE.get(token, token)))
    return found


def _trailing_run(numbers: list[int | None]) -> int:
    """Where the run of notes closing the text begins, or len(numbers) if none.

    A book that ends on its notes ends on a stretch of paragraphs numbered in
    order — 1, 2, 3 — and an edition that prints its notes without keeping the
    marks in the prose leaves nothing else to recognise them by.
    """
    start = len(numbers)
    at = len(numbers) - 1
    while at >= 0 and numbers[at] is not None:
        if at + 1 < len(numbers) and numbers[at + 1] != numbers[at] + 1:
            break
        start = at
        at -= 1
    return start if len(numbers) - start >= MIN_TRAILING_RUN else len(numbers)


def scan(paragraphs: list[str]) -> tuple[list[str], list[Note]]:
    """The prose without its notes, and the notes taken out of it."""
    numbers = [_opening(p) for p in paragraphs]
    pointed_at = references(paragraphs)
    from_here = _trailing_run(numbers)

    prose: list[str] = []
    notes: list[Note] = []
    for at, (paragraph, number) in enumerate(zip(paragraphs, numbers)):
        corroborated = number is not None and (number in pointed_at or at >= from_here)
        if corroborated:
            notes.append(Note(number, paragraph))
            continue
        kept, fused = _fused(paragraph)
        notes.extend(fused)
        if kept:
            prose.append(kept)
    return prose, notes
