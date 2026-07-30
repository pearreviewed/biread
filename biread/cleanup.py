"""Raw text -> chapters of clean paragraphs.

Strips Project Gutenberg / Wikisource cruft, rejoins hard-wrapped lines into
real paragraphs, and detects chapter breaks. Everything removed is reported
back so the caller can show it and confirm nothing real got eaten.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .numbering import chapter_number

GUTENBERG_START_RE = re.compile(
    r"^\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*\*\*\*\s*$",
    re.IGNORECASE | re.MULTILINE,
)
GUTENBERG_END_RE = re.compile(
    r"^\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*\*\*\*\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Tuned against a real fr.wikisource.org page (Voltaire, Micromégas/Texte
# entier) rather than guessed blind — but transcriptions vary by project, so
# check the stripped report when pointing this at a new source.
WIKISOURCE_LINE_RES = (
    re.compile(r"^\s*[◄◀]\s*\S.*$|^.*\S\s*[►▶]\s*$"),  # prev/next links
    re.compile(r"^\s*[▲^]\s*$"),  # back to top
    re.compile(r"^Catégorie(s)?\s*:", re.IGNORECASE),
    re.compile(r"^\S.*/Texte entier$"),  # the page's own title
    re.compile(r"^<\s+\S"),  # breadcrumb
)
WIKISOURCE_DOMAIN_NOTICE_RE = re.compile(
    r"domaine public|this work is in the public domain", re.IGNORECASE
)
# Fixed UI labels observed on a live Wikisource page's rendered menu/toolbar.
WIKISOURCE_UI_CHROME = frozenset({
    "Ajouter des langues", "Texte", "Source", "Discussion", "Lire", "Modifier",
    "Voir l’historique", "Voir l'historique", "Outils", "Apparence masquer",
    "Télécharger",
})

BARE_PAGE_NUMBER_RE = re.compile(r"^\[?\d{1,4}\]?$")

# The header Wikisource prints above a transcription — author, title, and the
# edition it was scanned from: "Micromégas, Garnier, 1877, tome 21 (p. 105-122)."
# A library catalogue entry, not the book. Left in place it rejoins into the
# first paragraph and is treated as prose: translated, and glossed at real cost.
# The parenthesised page range is the part worth matching; a year or a publisher
# could be anything, but prose does not carry "(p. 105-122)".
SOURCE_CITATION_RE = re.compile(r"\(\s*pp?\.\s*\d+(\s*[-–—]\s*\d+)?\s*\)")

# A bare year in parentheses standing alone in the front matter — "(1752)" — is
# the work's date, apparatus like the citation above it, not the book's opening
# line. Only stripped before any real text is kept; a parenthesised year inside
# prose is the author's own.
PUBLICATION_DATE_RE = re.compile(r"^\(\s*\d{3,4}\s*\)$")

# Wikisource marks each footnote with an upwards arrow linking back to its
# reference. Spelled as an escape because the bare glyph is easy to mistake for
# other arrows in an editor. Written U+2191.
FOOTNOTE_MARK = "↑"

# An inline reference: "il s'appelait Micromégas[1], nom qui convient…".
# Anchored on a preceding non-space so that a paragraph which *is* a footnote —
# "[1] From micros, small…" — keeps the marker that identifies it as one.
FOOTNOTE_REF_RE = re.compile(r"(?<=\S)\[\d{1,3}\]")
FOOTNOTE_BODY_RE = re.compile(r"^\[\d{1,3}\]\s")
# The heading word, then its number as any edition writes it: a roman numeral, an
# integer, or a spelled-out ordinal — including a hyphenated one ("dix-septième",
# "vingt-unième"), which the bare word branch used to sever at the hyphen and lose.
CHAPTER_RE = re.compile(
    r"^\s*(?:CHAPITRE|CHAPTER)\s+([IVXLCDM]+|\d+|[A-Za-zÀ-ÿ]+(?:-[A-Za-zÀ-ÿ]+)*)\s*\.?\s*$",
    re.IGNORECASE,
)
TITLE_MAX_LEN = 160


@dataclass
class Chapter:
    number: str | None  # numbering token as found ("I", "3"); None = leading section
    title: str | None
    paragraphs: list[str] = field(default_factory=list)
    #: Which part of the book this chapter belongs to, 1-based, where the edition
    #: divides itself into parts and starts numbering afresh in each. None where
    #: the chapters simply run 1..N. Madame Bovary has three, so its part II
    #: chapter I must not be mistaken for its part I chapter I.
    part: int | None = None


@dataclass(frozen=True)
class Removal:
    kind: str
    detail: str


def _strip_zero_width(line: str) -> str:
    return "".join(ch for ch in line if unicodedata.category(ch) != "Cf")


def strip_footnote_apparatus(text: str) -> tuple[str, list[Removal]]:
    """Cut the trailing block of Wikisource footnotes.

    Everything from the first footnote line to the end goes, not just the lines
    carrying the arrow: a note can run on across blank lines, and Micromégas
    ends with one whose body is a passage of Aristotle in Greek. Dropping only
    the marked lines would leave that stranded in the book as if it were prose.

    Whatever is cut is reported, so a source that puts notes somewhere other
    than the end shows up in the run's output rather than silently losing text.
    """
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.lstrip().startswith(FOOTNOTE_MARK):
            dropped = [ln for ln in lines[i:] if ln.strip()]
            return "\n".join(lines[:i]), [Removal(
                "Wikisource footnote apparatus",
                f"{len(dropped)} lines, from “{dropped[0][:60]}”",
            )]
    return text, []


def strip_boilerplate(raw: str) -> tuple[str, list[Removal]]:
    removed: list[Removal] = []
    text = raw

    start, end = GUTENBERG_START_RE.search(text), GUTENBERG_END_RE.search(text)
    if start and end and start.end() < end.start():
        header, footer = text[: start.end()], text[end.start() :]
        removed.append(Removal(
            "Project Gutenberg license header",
            f"{header.count(chr(10)) + 1} lines, through the START marker",
        ))
        removed.append(Removal(
            "Project Gutenberg license footer",
            f"{footer.count(chr(10)) + 1} lines, from the END marker",
        ))
        text = text[start.end() : end.start()]

    text, footnotes = strip_footnote_apparatus(text)
    removed.extend(footnotes)

    kept = []
    for line in text.split("\n"):
        stripped = _strip_zero_width(line).strip()
        if line.strip() and not stripped:
            removed.append(Removal("Invisible-character artifact line", line.strip()))
        elif stripped in WIKISOURCE_UI_CHROME:
            removed.append(Removal("Wikisource UI chrome", stripped))
        elif stripped and any(r.match(stripped) for r in WIKISOURCE_LINE_RES):
            removed.append(Removal("Wikisource nav/chrome line", stripped))
        elif stripped and WIKISOURCE_DOMAIN_NOTICE_RE.search(stripped):
            removed.append(Removal("Wikisource public-domain notice", stripped))
        else:
            kept.append(line)

    return "\n".join(kept).strip("\n"), removed


def _blocks(text: str) -> tuple[list[list[str]], list[Removal]]:
    """Blank-line-separated blocks, each as its surviving lines.

    Bare page numbers (a common Wikisource/OCR leftover) are dropped here,
    whether they sit alone or stacked with no blank line between them, along
    with footnote bodies and the inline markers that referred to them.
    """
    removed: list[Removal] = []
    out = []
    for block in re.split(r"\n\s*\n+", text.strip()):
        lines = []
        for line in block.splitlines():
            # Runs of spaces collapse to one: a PDF laid out with justified text
            # arrives full of them ("Pangloss     enseignait"), and no prose line
            # means anything by a gap wider than a single space.
            line = re.sub(r"\s+", " ", line).strip()
            if not line:
                continue
            if BARE_PAGE_NUMBER_RE.match(line):
                removed.append(Removal("Bare page-number artifact", line))
                continue
            lines.append(line)
        if not lines:
            continue
        # Only while nothing real has been kept yet: a citation belongs to the
        # transcription's header, and the same shape appearing mid-book would be
        # the author's own.
        if not out and any(SOURCE_CITATION_RE.search(ln) for ln in lines):
            removed.append(Removal("Source citation header", " ".join(lines)))
            continue
        if not out and len(lines) == 1 and PUBLICATION_DATE_RE.match(lines[0]):
            removed.append(Removal("Publication date", lines[0]))
            continue
        # Judged on the whole block, not its first line: a footnote is usually
        # hard-wrapped, and dropping only its opening line would strand the
        # rest in the book as though it were prose.
        if FOOTNOTE_BODY_RE.match(lines[0]):
            removed.append(Removal("Footnote text", " ".join(lines)))
            continue
        stripped = []
        for line in lines:
            line, count = FOOTNOTE_REF_RE.subn("", line)
            if count:
                removed.append(Removal("Footnote reference marker", line))
            stripped.append(line)
        out.append(stripped)
    return out, removed


def rejoin_paragraphs(text: str) -> tuple[list[str], list[Removal]]:
    """Blocks -> paragraphs, hard wraps rejoined with a single space."""
    blocks, removed = _blocks(text)
    return [" ".join(lines) for lines in blocks], removed


def _split_title(blocks: list[list[str]]) -> tuple[str | None, list[list[str]]]:
    """Peel a chapter's title or argument off the front of its blocks.

    A single short line before the body is a title — a heading, or the argument a
    chapter opens with. So is a *wrapped* argument: several lines that together
    stay short and are clearly shorter than the passage they introduce, which is
    how an edition like Candide sets a descriptive line under every chapter number
    and pypdf then breaks it across lines. What is left as body is the chapter's
    own opening prose — short sentences about as long as what follows them, which
    a title never is — and a one-block chapter, which is a paragraph, not a heading.
    """
    if len(blocks) < 2:
        return None, blocks
    head = " ".join(blocks[0])
    if not head or len(head) > TITLE_MAX_LEN:
        return None, blocks
    if len(blocks[0]) == 1 or len(head) * 2 <= len(" ".join(blocks[1])):
        return head, blocks[1:]
    return None, blocks


# A numeral standing alone on its line: as long as "eighteenth", no longer, so
# a short sentence is never mistaken for a heading.
HEADING_NUMERAL_MAX_LEN = 12


#: Lines between a chapter and the one that starts a new part's numbering. A part
#: boundary has a chapter behind it; adjacent numerals are a contents list.
RESTART_GAP = 3

#: A chapter has prose under it. Less than this between one heading and the next
#: means they are a list of chapters, not the chapters themselves. Small, because
#: a real chapter may be a paragraph long, and a contents list has essentially
#: nothing under each entry — a blank line, or a part label.
MIN_CHAPTER_TEXT = 10


def _spine(headings: list, lines: list[str]) -> list:
    """The real chapters among the candidate headings, whichever pattern found
    them: those with prose under them, from the first that starts the counting.

    Both a table of contents and the chapters it lists are headed identically —
    that is what a table of contents is — so both patterns need this, and an
    edition that writes "Chapter One" needs it exactly as much as one that writes
    a bare "I".
    """
    kept = _with_text_under_them(headings, lines)
    while kept and (chapter_number(kept[0][1]) or 0) > 2:
        kept.pop(0)
    return kept


def _with_text_under_them(candidates: list, lines: list[str]) -> list:
    """Candidates with a chapter's worth of prose beneath them.

    A table of contents is a column of the very numerals a chapter is headed by,
    and it comes first, so an edition that prints one offers a complete false
    spine before the real one. What separates them is that nothing is written
    under a table of contents: its entries sit line under line. Madame Bovary's
    EPUB lists thirty-five chapters this way, and the whole novel — every
    paragraph of it — was landing under the last of them.
    """
    kept = []
    for pos, heading in enumerate(candidates):
        end = candidates[pos + 1][0] if pos + 1 < len(candidates) else len(lines)
        under = [line.strip() for line in lines[heading[0] + 1 : end] if line.strip()]
        # Prose, not a label: what sits between two contents entries is a blank
        # line or a part heading set in capitals ("PART II."), never a sentence.
        if sum(map(len, under)) >= MIN_CHAPTER_TEXT and any(c.islower() for c in "".join(under)):
            kept.append(heading)
    return kept


def _numeral_headings(lines: list[str]) -> list[tuple[int, str]]:
    """Headings for an edition that marks chapters with a bare numeral and no
    heading word — a lone "I", "II" … "XXX", as a Gutenberg PDF sets Candide.

    A lone numeral is only a candidate; on its own it could be a page number or
    a figure in the prose. What makes it a heading is company: chapters number
    upward through the book, so the real headings are the longest run of
    candidates whose values strictly increase in reading order, starting from
    the top. A stray numeral that does not fit that run is left as prose.
    """
    candidates = [
        (i, s, value)
        for i, line in enumerate(lines)
        if (s := line.strip()) and len(s) <= HEADING_NUMERAL_MAX_LEN
        and (value := chapter_number(s)) is not None
    ]
    if len(candidates) < 3:
        return []

    # Longest ascending run, breaking ties toward consecutive numbering: given a
    # book that reads I, II, V, III, both (I, II, V) and (I, II, III) ascend and
    # run three long, but chapters are numbered without gaps, so the run that
    # steps by one wins and the stray V is left as prose. Each run is scored
    # (length, number of +1 steps) and the best carries.
    # A run may also begin again at 1: a book in parts numbers its chapters
    # afresh in each, so I..IX, I..XV, I..XI is one spine of thirty-five and not
    # three rival spines of nine, fifteen and eleven.
    score = [(1, 0)] * len(candidates)
    came_from = [-1] * len(candidates)
    for j in range(len(candidates)):
        for k in range(j):
            ascending = candidates[k][2] < candidates[j][2]
            # A restart is a part boundary, and a part boundary has a chapter
            # behind it. Without the distance, a chapter's own title set in
            # capitals ("I" then "FIRST") reads as chapter one starting over,
            # and so does every line of a table of contents.
            restarts = candidates[j][2] == 1 and candidates[j][0] - candidates[k][0] > RESTART_GAP
            if ascending or restarts:
                length, steps = score[k]
                consecutive = steps + (candidates[j][2] == candidates[k][2] + 1 or restarts)
                if (length + 1, consecutive) > score[j]:
                    score[j] = (length + 1, consecutive)
                    came_from[j] = k
    end = max(range(len(candidates)), key=score.__getitem__)

    run: list[tuple[int, str]] = []
    while end != -1:
        i, token, _ = candidates[end]
        run.append((i, token))
        end = came_from[end]
    run.reverse()

    # Several of them, and a spine rather than two coincidental numerals. A stray
    # high numeral left over from a table of contents can otherwise anchor the run
    # ahead of the real first chapter — Madame Bovary keeps one "XI" that way.
    run = _spine(run, lines)
    if len(run) < 3:
        return []
    return run


def detect_chapters(text: str) -> tuple[list[Chapter], list[Removal]]:
    """Split cleaned text into chapters at their heading lines.

    Headings are "Chapitre/Chapter N" lines where an edition writes them out;
    where it marks a chapter with only a bare numeral, they are found by the
    ascending run of those instead (`_numeral_headings`).

    A file with no headings at all is valid input: everything comes back as one
    untitled chapter. Numbering need not be contiguous.

    Headings are found at the line level, not the rejoined-paragraph level,
    because a heading and its subtitle sometimes share a block with no blank
    line between them (Wikisource) and sometimes sit in separate blocks
    (Project Gutenberg) — both need the same treatment.
    """
    removed: list[Removal] = []
    lines = text.split("\n")
    headings = [
        (i, m.group(1))
        for i, line in enumerate(lines)
        if (m := CHAPTER_RE.match(line.strip()))
    ]
    headings = _spine(headings, lines) if len(headings) >= 2 else headings
    if len(headings) < 2:
        headings = _numeral_headings(lines) or headings

    def section(start: int, end: int) -> list[list[str]]:
        blocks, r = _blocks("\n".join(lines[start:end]))
        removed.extend(r)
        return blocks

    if not headings:
        paragraphs = [" ".join(b) for b in section(0, len(lines))]
        return [Chapter(number=None, title=None, paragraphs=paragraphs)], removed

    chapters: list[Chapter] = []
    preamble = section(0, headings[0][0])
    if preamble:
        chapters.append(Chapter(None, None, [" ".join(b) for b in preamble]))

    parts = _parts(headings)
    for pos, (line_idx, number) in enumerate(headings):
        end = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
        title, body = _split_title(section(line_idx + 1, end))
        chapters.append(Chapter(number, title, [" ".join(b) for b in body], parts[pos]))

    return chapters, removed


def _parts(headings: list[tuple[int, str]]) -> list[int | None]:
    """Which part each heading belongs to, counted from where the numbering
    starts over.

    A book that simply runs 1..N is in no parts at all and every chapter gets
    None, so nothing changes for the books that do. Only where the numbers fall
    back on themselves is a boundary read, and then the chapter's identity is the
    pair — part two's chapter one is not part one's.
    """
    numbers = [chapter_number(token) for _, token in headings]
    part = 1
    out: list[int | None] = []
    for pos, number in enumerate(numbers):
        previous = numbers[pos - 1] if pos else None
        if previous is not None and number is not None and number <= previous:
            part += 1
        out.append(part)
    return out if part > 1 else [None] * len(headings)


def clean(raw: str, from_pdf: bool = False) -> tuple[list[Chapter], list[Removal]]:
    """Raw text -> (chapters, everything that was removed).

    `from_pdf` admits the repairs that only a PDF needs, and that would be a
    liberty taken with any format able to mark its own paragraphs.
    """
    from .normalize import repair
    from .notes import scan

    text, repaired = repair(raw, from_pdf)
    text, removed = strip_boilerplate(text)
    chapters, more = detect_chapters(text)

    # Per chapter, because that is where an edition puts its notes — and because a
    # marker restarts at 1 in each, so the whole book read at once would take one
    # chapter's reference as corroboration for another's.
    for chapter in chapters:
        chapter.paragraphs, notes = scan(chapter.paragraphs)
        for note in notes:
            more.append(Removal("Note", f"[{note.number}] {note.text[:70]}"))

    return chapters, repaired + removed + more
