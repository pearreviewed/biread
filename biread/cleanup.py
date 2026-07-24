"""Raw text -> chapters of clean paragraphs.

Strips Project Gutenberg / Wikisource cruft, rejoins hard-wrapped lines into
real paragraphs, and detects chapter breaks. Everything removed is reported
back so the caller can show it and confirm nothing real got eaten.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

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
CHAPTER_RE = re.compile(
    r"^\s*(?:CHAPITRE|CHAPTER)\s+([IVXLCDM]+|\d+|[A-Za-zÀ-ÿ]+)\s*\.?\s*$",
    re.IGNORECASE,
)
TITLE_MAX_LEN = 160


@dataclass
class Chapter:
    number: str | None  # numbering token as found ("I", "3"); None = leading section
    title: str | None
    paragraphs: list[str] = field(default_factory=list)


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
    """Peel a chapter subtitle off the front of a chapter's blocks.

    A title is a block of exactly one source line, short enough to be a title,
    with body text after it. Requiring a single *line* is what keeps a short
    opening sentence from being promoted to a title: real titles are never
    hard-wrapped, and a one-block chapter is a body paragraph, not a heading.
    """
    if len(blocks) > 1 and len(blocks[0]) == 1 and len(blocks[0][0]) <= TITLE_MAX_LEN:
        return blocks[0][0], blocks[1:]
    return None, blocks


def detect_chapters(text: str) -> tuple[list[Chapter], list[Removal]]:
    """Split cleaned text into chapters at 'Chapitre/Chapter N' heading lines.

    A file with no such headings is valid input: everything comes back as one
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

    for pos, (line_idx, number) in enumerate(headings):
        end = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
        title, body = _split_title(section(line_idx + 1, end))
        chapters.append(Chapter(number, title, [" ".join(b) for b in body]))

    return chapters, removed


def clean(raw: str) -> tuple[list[Chapter], list[Removal]]:
    """Raw text -> (chapters, everything that was removed)."""
    text, removed = strip_boilerplate(raw)
    chapters, more = detect_chapters(text)
    return chapters, removed + more
