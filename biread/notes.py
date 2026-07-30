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
        else:
            prose.append(paragraph)
    return prose, notes
