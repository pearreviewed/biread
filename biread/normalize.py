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
from collections import Counter

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
                # rstrip, not strip: the leading space is the heading's own
                # indent, and a book that marks its paragraphs that way is about
                # to be read for it.
                out.append(f"{line.rstrip()} {lines[look].strip()}")
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
    blocks = _blocks_of(text)
    if not blocks:
        return False
    lengths = sorted(len(b) for b in blocks)
    return lengths[len(lengths) // 2] > UNBROKEN_BLOCK


def _blocks_of(text: str) -> list[str]:
    return [b for b in re.split(r"\n\s*\n+", text.strip()) if b.strip()]


#: What share of a file's blocks must be a single line before its blank lines are
#: read as line breaks. Near enough all of them: every book in the corpus sits
#: between 25% and 38%, and the conversion that prompted this sits at 100%.
LINE_BLOCK_SHARE = 0.9

#: How long such a block may run and still be a typeset line rather than a
#: paragraph. A printed line is sixty characters and a paragraph is hundreds:
#: Micromégas arrives as a text file whose every paragraph is one unwrapped line
#: of 831 characters, which is the case this must not touch.
LINE_BLOCK = 200

#: Enough blocks to have a shape at all. Below this a file is a fragment and its
#: proportions say nothing.
ENOUGH_BLOCKS = 20

#: How few of those lines may finish a sentence. Only a paragraph's last line
#: closes, so a column of type closes about once per paragraph — the conversion
#: that prompted this scores 27%, and the corpus, whose blocks really are
#: paragraphs, scores 60% to 89%. The gate sits in the gap.
LINE_BLOCK_CLOSES = 0.4


def _broke_every_line(text: str) -> bool:
    """Does this file put a paragraph break at the end of every *line*?

    The mirror of `_never_broke`, and the same accident seen from the other side.
    A PDF poured into Word comes back either with every paragraph mark gone or
    with one after each typeset line — the reader who brought La Nausée as two
    `.docx` files got one of each, the French flat as a single block of 443,298
    characters and the English cut into 9,271 pieces averaging 57.

    Neither file is describing itself. A book is not set in fifty-seven character
    paragraphs, and a run of them all ending at the measure is a column of type,
    not prose. Read as paragraphs they align as fragments: the reader's English
    page was `The best thing would be to write down events from day`, cut mid
    sentence, over and over.

    Four marks have to agree, and the last is the one that decides. Nearly every
    block is a single line; that line is a line long rather than a paragraph long,
    which keeps out Micromégas — a text file whose every paragraph is one
    unwrapped line of 831 characters; those lines run to the *full measure*; and
    most of them **do not finish a sentence**.

    The last two are `_unfuse_paragraphs`'s own reasoning read backwards. A line
    stopping short of the measure stopped because its paragraph ended; these
    neither stop short nor stop speaking, so they did not end paragraphs, and the
    break after each of them was put there by something other than the author.
    Only a paragraph's final line closes, so a column of type closes about once
    per paragraph — the broken file scores 27%, and every book in the corpus,
    whose blocks really are paragraphs, scores 60% to 89%.
    """
    blocks = _blocks_of(text)
    if len(blocks) < ENOUGH_BLOCKS:
        return False
    singles = [b.strip() for b in blocks if "\n" not in b.strip()]
    if len(singles) < len(blocks) * LINE_BLOCK_SHARE:
        return False
    lengths = sorted(len(s) for s in singles)
    typical = lengths[len(lengths) // 2]
    if not LINE_BLOCK >= typical >= _measure(text.split("\n")) * SHORT_LINE:
        return False
    closing = sum(1 for s in singles if CLOSED_RE.search(s))
    return closing < len(singles) * LINE_BLOCK_CLOSES


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


#: What share of a file's lines must open at one and the same indent before that
#: indent is read as the file's paragraph mark. Every verified book in the corpus
#: sits under 3% — a stray centred heading, a page number — where the two scans
#: that prompted this sit at 18% and 25%. The gap is wide enough that the exact
#: figure does not matter; what matters is that it is a convention or it is noise.
INDENT_SHARE = 0.10


def _indent_mark(lines: list[str]) -> int:
    """The column at or beyond which a line begins a paragraph, or 0 for none.

    A printed page marks its paragraphs twice: by where a line *ends* — the
    signal `_unfuse_paragraphs` reads — and by where the next one *begins*. The
    second is the better of the two, because it is the compositor stating the
    break rather than us inferring one, and an extractor that keeps leading
    whitespace hands it over intact.

    A file has the convention when one indent accounts for a real share of its
    lines and is still outnumbered by the flush ones — a paragraph runs to
    several lines, so its openings must be the minority. Anything else is a
    handful of centred headings, and reading those as a convention would cut the
    book at every one of them.
    """
    indents = [len(line) - len(line.lstrip(" ")) for line in lines if line.strip()]
    if not indents:
        return 0
    counts = Counter(indents)
    flush, at_flush = counts.most_common(1)[0]
    deeper = [(col, n) for col, n in counts.items() if col > flush]
    if not deeper:
        return 0
    indent, at_indent = max(deeper, key=lambda pair: pair[1])
    if at_indent < len(indents) * INDENT_SHARE or at_indent >= at_flush:
        return 0
    # Halfway between the two columns, so a scan that wanders a space either way
    # still lands on the right side of it.
    return flush + (indent - flush + 1) // 2


#: A line that has finished saying something: a sentence's own punctuation, or
#: the colon or dash a line introducing speech closes on — the same pair
#: `segment.SPEECH_RE` reads, and for the same reason.
CLOSED_RE = re.compile(r"[.!?…:;—–][\"”»’')\]]?$")

#: A line that starts saying something: a capital, or the mark that introduces
#: speech before one.
OPENED_RE = re.compile(r"[—–]\s|[\"“«'(]?[A-ZÀ-Þ]")

#: How much of the measure a flush line may run to and still be a heading rather
#: than the last line of a paragraph. Half, because a heading is set on its own
#: and a paragraph's final line is as long as its sentence happened to leave it —
#: `JEUDI.` is seven characters against a measure of ninety.
HEADING_LINE = 0.5


def _stands_alone(text: str, above: str, below: str, mark: int, measure: int) -> bool:
    """Is this flush line a heading, rather than the tail of the paragraph above?

    A file that indents says where its paragraphs begin, and says nothing at all
    about the lines that begin no paragraph — so a heading, which is set flush,
    arrives with no mark of its own and joins whatever preceded it. That is how
    both scans of Nausea lost the dates its diary is built out of: `Il ne faut pas
    avoir peur. JEUDI.` and `1 must not be afraid. Thursday:`, 21 of them in the
    French and 18 in the English.

    Three conditions, and the three together are what make it corroboration
    rather than shape. The line is short, well inside the measure. The line below
    it opens a paragraph at the indent, so it is the last thing before a fresh
    start. And what stands above it has finished — a blank line, or a closed
    sentence — so the line is not a continuation of anything. A paragraph's own
    last line fails the middle test or the one above it, which is why every book
    in the corpus comes out to the paragraph unchanged.
    """
    if not measure or len(text) >= measure * HEADING_LINE:
        return False
    if not CLOSED_RE.search(text):
        return False
    below_opens = bool(below) and len(below) - len(below.lstrip(" ")) >= mark
    return below_opens and (not above or bool(CLOSED_RE.search(above)))


def _split_on_indent(lines: list[str], mark: int) -> tuple[list[str], int]:
    """Cut the file where it says its paragraphs begin, and only there.

    The blank lines go with them. In a file that indents, a blank line is the
    scanner's leading and nothing else: the second Nausea scan sets one after
    almost every line it happens to have measured tall, three of them inside the
    novel's opening paragraph. Trusting both marks at once cut that book into
    3,166 pieces against the other edition's 1,563; trusting the indent alone
    gives 2,182, and the two editions then agree on 97% of the openings they
    share instead of 60%.

    The indent is taken at its word unless the prose plainly runs straight
    through it — the line above stopping mid-clause *and* the line below resuming
    mid-clause. That is a scanner mismeasuring a margin, not a compositor marking
    a paragraph, and on the same pair it takes the two editions from 2,182
    paragraphs against 1,563 to 1,761 against 1,527, agreeing on 92% of their
    openings each way instead of 97% and 81%.

    A flush line that begins no paragraph is still cut where it plainly begins
    nothing else — see `_stands_alone`, which is what gives a diary back the dates
    it is written in.
    """
    measure = _measure(lines)
    out: list[str] = []
    marked = 0
    previous = ""
    for i, line in enumerate(lines):
        if not line.strip():
            previous = ""
            continue
        text = line.strip()
        if len(line) - len(line.lstrip(" ")) >= mark and out:
            if CLOSED_RE.search(out[-1].strip()) or OPENED_RE.match(text):
                out.append("")
                marked += 1
        elif out:
            below = next((l for l in lines[i + 1:] if l.strip()), "")
            if _stands_alone(text, previous, below, mark, measure):
                out.append("")
                marked += 1
        out.append(line)
        previous = text
    return out, marked


def repair(raw: str, from_pdf: bool = False) -> tuple[str, list[Removal]]:
    """Raw extractor text -> (repaired text, what was repaired).

    `from_pdf` admits the repairs that only a PDF always needs; a file of any
    format whose paragraphing was lost in conversion gets them too, whichever way
    it was lost — see `_unfuse_paragraphs`, `_never_broke` and `_broke_every_line`.
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

    # Before anything reads the blank lines as boundaries: where they fall after
    # every typeset line they are line breaks, and taking them out leaves
    # ordinary hard-wrapped text for the rest of this to repair.
    line_broken = _broke_every_line(text)
    if line_broken:
        was = len(_blocks_of(text))
        lines = [line for line in lines if line.strip()]
        removed.append(Removal(
            "Line breaks read as paragraph breaks",
            f"{was} one-line blocks rejoined; the file marked every line, not every paragraph",
        ))

    mark = _indent_mark(lines)
    lines, joined = _rejoin_split_headings(lines)
    if joined:
        removed.append(Removal("Split heading rejoined", f"{joined} heading(s) reunited with their numeral"))

    lines, healed = _dehyphenate(lines)
    if healed:
        removed.append(Removal("Line-broken word rejoined", f"{healed} hyphenated word(s) made whole"))

    if mark:
        lines, marked = _split_on_indent(lines, mark)
        if marked:
            removed.append(Removal(
                "Paragraph indent read",
                f"{marked} paragraph(s) marked by an indent, at column {mark} and beyond",
            ))
    elif from_pdf or line_broken or _never_broke(text):
        lines, split = _unfuse_paragraphs(lines)
        if split:
            removed.append(Removal(
                "Paragraph break restored", f"{split} run-together paragraph(s) separated"
            ))

    return "\n".join(lines), removed
