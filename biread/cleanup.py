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

# An inline reference: "il s'appelait Micromégas[1], nom qui convient…", and
# "…ce serait si [4]", which the French Nausea sets off with a space where
# Micromégas glues it to the word. Anchored on *anything* preceding it rather
# than on a non-space, so a paragraph which *is* a footnote — "[1] From micros,
# small…" — still keeps at its head the marker that identifies it as one.
FOOTNOTE_REF_RE = re.compile(r"(?<=.)\[\d{1,3}\]")
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
        # Punctuation alone is not prose. A scan leaves stray marks standing as
        # paragraphs of their own — a colon, `;;`, `: :`, `."` — and each takes an
        # alignment slot facing a real paragraph of the other edition. A
        # typographic break (`* * *`) goes with them, being a mark and not a
        # sentence, and like every other removal it is named on the terminal
        # rather than dropped quietly.
        #
        # Deliberately not "nothing with a letter in it", which reads better and
        # takes real text: that rule dropped a line of Roquentin's dates
        # (`1924, 1925,`) and the `(1857)` off Bovary's title page, and on the
        # Internet Archive Nausea it took 105 paragraphs where this takes 35. What
        # it would additionally catch there is `44 44`, which is OCR reading a
        # quotation mark as the page number beside it — untidy, and not worth a
        # rule that cannot tell it from a year.
        if not any(c.isalnum() for c in "".join(lines)):
            removed.append(Removal("Not prose", " ".join(lines)))
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

#: How much of a bare-numeral spine has to step by one. Ascending is not enough
#: on its own: a PDF's page numbers ascend too, and 99 and 146 beside a stray
#: "one." at the end of a wrapped sentence read as a four-chapter Nausea — which
#: then had its first third trimmed away as front matter. Not all of it, because
#: an extractor that loses a single heading would otherwise break a real spine.
MIN_CONSECUTIVE = 0.5


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


def _written_as_a_heading(token: str) -> bool:
    """A bare heading is set as one: "IV", "12", "One" — never "one.", which is
    the tail of a sentence a PDF wrapped onto a line of its own. Digits carry no
    case and are judged by their company alone; letters must be capitalized."""
    letters = [c for c in token if c.isalpha()]
    return not letters or letters[0].isupper()


#: How much of a bare-numeral spine has to have a chapter's opening under it.
#: Every edition in the corpus scores 100%; the printed page numbers of a book
#: with no chapters at all score 15%, so the exact figure is immaterial.
MIN_OPENING = 0.8

#: How a chapter's first line begins: a capital, or the mark that introduces
#: speech before one. Generous on purpose — the cost of failing to recognise a
#: real opening is a lost chapter, and the cost of recognising a false one is
#: only that this test declines to settle the question.
CHAPTER_OPENING_RE = re.compile(r"[—–]\s|[\"“«'(]?[A-ZÀ-Þ]")


def _opens_a_chapter(run: list[tuple[int, str]], lines: list[str]) -> bool:
    """Does prose *begin* under each numeral, or merely carry on past it?

    The one thing every chapter does, whatever the edition, is start a sentence.
    A number stamped into the middle of a page does not: the line under it
    resumes whatever was already running — mid-clause, lower case, often
    mid-word.

    This is what tells a spine from a set of page numbers, which nothing else
    could. Page numbers ascend, step by one without a gap, and have a page of
    prose under each — they satisfy every other test here perfectly, and the
    scanned Nausea that prompted this came back as a hundred and seventy-five
    chapters of a novel that has none.
    """
    def under(index: int) -> str:
        return next((line.strip() for line in lines[index + 1:] if line.strip()), "")

    opened = sum(1 for index, _ in run if CHAPTER_OPENING_RE.match(under(index)))
    return opened >= len(run) * MIN_OPENING


def _steps_by_one(run: list[tuple[int, str]]) -> bool:
    """A spine numbers its chapters without gaps. A part boundary counts as a
    step, since a book in parts begins again at one."""
    values = [chapter_number(token) or 0 for _, token in run]
    steps = [later == earlier + 1 or later == 1 for earlier, later in zip(values, values[1:])]
    return sum(steps) > len(steps) * MIN_CONSECUTIVE


def _numeral_headings(lines: list[str]) -> list[tuple[int, str]]:
    """Headings for an edition that marks chapters with a bare numeral and no
    heading word — a lone "I", "II" … "XXX", as a Gutenberg PDF sets Candide.

    A lone numeral is only a candidate; on its own it could be a page number or
    a figure in the prose. What makes it a heading is company: chapters number
    upward through the book, so the real headings are the longest run of
    candidates whose values strictly increase in reading order, starting from
    the top, and step by one oftener than not. A stray numeral that does not fit
    that run is left as prose.
    """
    candidates = [
        (i, s, value)
        for i, line in enumerate(lines)
        if (s := line.strip()) and len(s) <= HEADING_NUMERAL_MAX_LEN
        and _written_as_a_heading(s)
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
    if len(run) < 3 or not _steps_by_one(run) or not _opens_a_chapter(run, lines):
        return []
    return run


#: The days a diary is kept in. Two languages because that is what the corpus
#: has and what a bilingual reader pairs; a third is another row.
WEEKDAYS = frozenset({
    "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
})

#: How long a dated heading may run. Long enough for the ones that say more than
#: the day — "JEUDI MATIN, À LA BIBLIOTHÈQUE.", "MERCREDI : Mon dernier jour à
#: Bouville." — and far short of a sentence that merely mentions a Thursday.
DATED_HEADING_MAX_LEN = 60

WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]+")

#: A line that opens as speech. A day named inside dialogue is a character
#: saying it — «— Toi, tu me l'as dit dimanche.», "You did. You told me Sunday."
#: — and both editions of Nausea set such lines apart exactly as they set a
#: heading, so nothing about their shape tells them apart. What tells them apart
#: is that a heading is not spoken.
SPOKEN_RE = re.compile(r"^[—–\"“«]")

#: The other end of the same line, because a scan loses the first mark and keeps
#: the last. OCR read the opening quotation of `“No, Tuesday, you know because of
#: the …”` as the page number stamped beside it and handed over `44No, Tuesday,
#: you know because of the . ..”`, which opens on a digit and passes `SPOKEN_RE`
#: untouched. The mark that closes the speech came through intact.
CLOSES_SPEECH_RE = re.compile(r"[\"”»]\s*$")

#: What a line above a heading looks like when the paragraph it belongs to has
#: ended. A printed page marks a heading with space above and below it, and a scan
#: hands over only the space below: a heading set at the top of a page arrives with
#: the foot of the previous page's last paragraph directly above it, and that lost
#: 7 of the 20 entries in the Internet Archive scan of the 1949 Nausea. Reading the
#: sentence instead is the same evidence `normalize._stands_alone` reads, in the
#: same order.
FINISHED_RE = re.compile(r"[.!?:;][\"”»']?$")

#: How many words a dateline may put in front of its day. One: "Shrove Tuesday:",
#: "MARDI GRAS". A sentence about a day puts the day further in — "The usual Sunday
#: sauerkraut ?" is the third word, and it was being read as a chapter heading.
DAY_AT_MOST = 2


def _dated_headings(lines: list[str]) -> list[tuple[int, str]]:
    """Headings for a book divided by date rather than by number.

    A diary has a spine and no numbers in it. Nausea is the case: thirty-odd
    entries headed `JEUDI.` in the French and `Thursday:` in the English, and
    nothing else marking where one ends and the next begins. Read as no spine at
    all, the novel aligns as a single run of fifteen hundred paragraphs with
    nothing to pin it to; read as a spine, it pairs section against section like
    any other book.

    A day name is not enough on its own, and this is where saying so is not
    academic: prose mentions Thursdays constantly, and the French Nausea offers
    twenty wrapped lines carrying "dimanche" or "samedi" mid-sentence against
    twenty-two real headings — enough to sink the spine on shape alone.

    What separates them is that a heading is *set apart*: space below it, and
    above it either space or a paragraph that has finished. That mark comes from
    the file rather than from us — it is the compositor's, the same evidence
    `normalize._stands_alone` reads, in the same order. Demanding a blank line on
    *both* sides is what a clean file offers and a scan does not: a heading set at
    the top of a page arrives with the previous page's last line directly above
    it, and that lost seven of the twenty entries in a scan of the 1949 Nausea.
    On top of it the usual company: the line is short, it is not spoken at either
    end, it opens on its day rather than merely naming one, several of them run
    through the book, and a chapter's worth of prose *begins* under each rather
    than carrying on past it (`_opens_a_chapter`).
    """
    def blank(i: int) -> bool:
        return not 0 <= i < len(lines) or not lines[i].strip()

    def set_apart(i: int) -> bool:
        return blank(i + 1) and (blank(i - 1) or bool(FINISHED_RE.search(lines[i - 1].strip())))

    def dateline(text: str) -> bool:
        return any(w.lower() in WEEKDAYS for w in WORD_RE.findall(text)[:DAY_AT_MOST])

    # Measured as the file sets it, printed as the book reads it. A dated heading
    # is the one heading that keeps its own words, so it is the one place a scan's
    # spacing reaches the page — `Tuesday,    30  January:` is how OCR reads a
    # printed line, and the body escapes it only because `_blocks` collapses runs
    # of spaces on its way past. The length bound stays on the raw line, because
    # collapsing first loosens it by however far the scanner spaced the page out:
    # a 74-character line of newspaper small ads came under 60 that way and was
    # read as a chapter of the novel.
    candidates = [
        (i, " ".join(s.split()))
        for i, line in enumerate(lines)
        if (s := line.strip()) and len(s) <= DATED_HEADING_MAX_LEN and set_apart(i)
        and not SPOKEN_RE.match(s) and not CLOSES_SPEECH_RE.search(s)
        and dateline(s)
    ]
    run = _with_text_under_them(candidates, lines)
    if len(run) < 3 or not _opens_a_chapter(run, lines):
        return []
    return run


def detect_chapters(text: str) -> tuple[list[Chapter], list[Removal]]:
    """Split cleaned text into chapters at their heading lines.

    Headings are "Chapitre/Chapter N" lines where an edition writes them out;
    where it marks a chapter with only a bare numeral, they are found by the
    ascending run of those instead (`_numeral_headings`); and where it numbers
    nothing but keeps a diary, by the dates it is kept in (`_dated_headings`).
    A dated heading *is* its own title, where a numbered one names its title on
    the line beneath.

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
    dated = _dated_headings(lines) if len(headings) < 2 else []
    headings = dated or headings

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
    for pos, (line_idx, token) in enumerate(headings):
        end = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
        blocks = section(line_idx + 1, end)
        if dated:
            chapters.append(Chapter(None, token, [" ".join(b) for b in blocks]))
            continue
        title, body = _split_title(blocks)
        chapters.append(Chapter(token, title, [" ".join(b) for b in body], parts[pos]))

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
