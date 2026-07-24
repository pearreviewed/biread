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

Without a generated translation to pivot on, the two editions are anchored to
each other instead, on the names and numbers that survive translation
(`anchor.py`). Only where even that finds too little to go on does this fall
back to distributing proportionally, which is a rough approximation.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

from .anchor import align_by_anchors
from .cleanup import Chapter
from .errors import AlignmentError
from .numbering import chapter_number
from .translate import hash_text

# Digits included on purpose: dates, editions and quantities are among the
# most discriminating tokens a paragraph has.
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
# A published edition sets its notes as ordinary paragraphs; the source has no
# counterpart for them, so they are apparatus and never a translation of anything.
FOOTNOTE_RE = re.compile(r"^\[\d+\]")
MIN_SIMILARITY = 0.34  # a third of the shorter text must be shared to count
MIN_SHARED_WORDS = 2   # one word in common is coincidence, not correspondence
# Below this share of the French left with a counterpart, the published column is
# more gap than text: the reader is told plainly rather than shown a near-empty page.
MIN_COVERAGE = 0.7

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
    total: int = 0  # French paragraphs a published counterpart was sought for
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

    @property
    def coverage(self) -> float:
        """The share of the French that found a counterpart, 0 to 1."""
        if not self.total:
            return 0.0
        return (self.total - self.unmatched) / self.total

    @property
    def degraded(self) -> bool:
        """Too little of the book lined up to present the column without warning."""
        return self.total > 0 and self.coverage < MIN_COVERAGE


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


def _match_by_length(french: list[str], published: list[str]) -> list[str]:
    """Distribute published paragraphs by length rather than by count.

    With no vocabulary or number to go on, the surest thing two editions of a
    passage still share is shape: a long paragraph translates long and a short
    one short. So a French paragraph holding a given fraction of its side's text
    (measured in characters) draws the published paragraphs holding that same
    fraction of theirs — a long paragraph pulls the long stretch of English, a
    short one the short — where the count-proportional split ignores size and
    can hand a two-line paragraph the same share as a two-page one.

    Falls back to the count-proportional split when there is nothing to weigh by:
    equal counts pair one-to-one, and fewer published than French is a merge,
    whose text is shown across the paragraphs it was merged from.
    """
    n, m = len(french), len(published)
    if n == 0:
        return []
    if m == 0:
        return [""] * n
    if m <= n:
        return _distribute(french, published)

    left_lengths = [len(p) or 1 for p in french]
    total_left = sum(left_lengths)
    bounds, running = [], 0
    for length in left_lengths:
        running += length
        bounds.append(running / total_left)

    total_right = sum(len(p) or 1 for p in published)
    groups: list[list[str]] = [[] for _ in range(n)]
    running = 0
    for text in published:
        weight = len(text) or 1
        midpoint = (running + weight / 2) / total_right
        running += weight
        groups[min(bisect.bisect_left(bounds, midpoint), n - 1)].append(text)
    return [" ".join(g) for g in groups]


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


# The signatures of matter that brackets a book without being it: a Gutenberg
# volunteer credit, a transcriber's note, a licence. Matched at the head of a
# paragraph, where these always announce themselves.
FRONT_MATTER_RES = (
    re.compile(r"^\s*produced by", re.IGNORECASE),
    re.compile(r"transcriber'?s?\s*[’']?s?\s*note", re.IGNORECASE),
    re.compile(r"project gutenberg", re.IGNORECASE),
    re.compile(r"e-?text (?:prepared|produced) by", re.IGNORECASE),
    re.compile(r"^\s*(?:copyright|©)\b", re.IGNORECASE),
    re.compile(r"all rights reserved", re.IGNORECASE),
    re.compile(r"first (?:published|edition)", re.IGNORECASE),
)

# A genuine front section is part of the book, not garbage before it: an
# introduction or preface is a valid place to open, so it stops the trimming.
FRONT_SECTION_RE = re.compile(
    r"^\s*(introduction|pr[ée]face|preface|prologue|foreword|avant-propos|avertissement)\b",
    re.IGNORECASE,
)


def _is_front_matter(paragraph: str) -> bool:
    """Whether a leading paragraph is apparatus rather than the book itself.

    Conservative on purpose: only a paragraph that positively matches a known
    boilerplate signature, or reads as a title-page fragment (a short line in
    capitals, no sentence to it), is called matter. Anything that looks like a
    real sentence — or names a front section the reader would want — is the book,
    and stops the trimming, so an opening line is never mistaken for garbage.
    """
    text = paragraph.strip()
    if not text or FRONT_SECTION_RE.match(text):
        return False
    if any(r.search(text) for r in FRONT_MATTER_RES):
        return True
    letters = [c for c in text if c.isalpha()]
    title_page_fragment = (
        len(text) <= 60
        and letters
        and not any(c.islower() for c in letters)
        and not text.rstrip().endswith((".", "!", "?"))
    )
    return bool(title_page_fragment)


def _strip_leading_matter(chapters: list[Chapter]) -> list[Chapter]:
    """Drop leading boilerplate paragraphs so a book with no numbered chapters
    still opens on its first real text rather than a title page."""
    result: list[Chapter] = []
    trimmed = False
    seeking = True
    for chapter in chapters:
        if not seeking:
            result.append(chapter)
            continue
        start = 0
        while start < len(chapter.paragraphs) and _is_front_matter(chapter.paragraphs[start]):
            start += 1
        if start < len(chapter.paragraphs):
            result.append(Chapter(chapter.number, chapter.title, chapter.paragraphs[start:]))
            seeking = False
            trimmed = trimmed or start > 0
        else:
            trimmed = trimmed or bool(chapter.paragraphs)
    if not trimmed:
        return chapters
    return result or chapters


def trim_matter(chapters: list[Chapter]) -> list[Chapter]:
    """Drop what brackets a book without being the book: a title page, a table of
    contents, a publisher's notice or a critic's introduction in front; a licence
    or endnotes behind. These are exactly the sections cleanup could not number.

    Leaving them in is what puts two editions permanently out of step — one
    edition's forty-page introduction would otherwise shift every paragraph after
    it. Where chapters are numbered, everything outside the numbered run goes.
    Where none are, the book is not left untouched but combed for the boilerplate
    that opens a file — so it still starts on real text, or on a named front
    section, rather than on "Produced by …".
    """
    numbered = [i for i, c in enumerate(chapters) if chapter_number(c.number) is not None]
    if not numbered:
        return _strip_leading_matter(chapters)
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


def _chapter_agreements(
    french: list[Chapter], published: list[Chapter]
) -> list[tuple[int, int]]:
    """Where each shared chapter number begins, counted in paragraphs.

    Fed to the anchoring pass as agreements it could not have found on its own:
    a chapter number is the surest correspondence two editions offer, when both
    of them happen to mark one.
    """
    def starts(chapters: list[Chapter]) -> dict[int, int]:
        found: dict[int, int] = {}
        index = 0
        for chapter in chapters:
            number = chapter_number(chapter.number)
            if number is not None and number not in found:
                found[number] = index
            index += len(chapter.paragraphs)
        return found

    here, there = starts(french), starts(published)
    return [(here[n], there[n]) for n in sorted(here.keys() & there.keys())]


def _by_anchor(
    french: list[Chapter], published: list[Chapter], report: AlignmentReport
) -> dict[str, str] | None:
    """Match two editions on the names and numbers they share, or None."""
    fr_paragraphs = [p for c in french for p in c.paragraphs]
    pub_paragraphs = [
        p for c in published for p in c.paragraphs if not FOOTNOTE_RE.match(p)
    ]
    texts = align_by_anchors(
        fr_paragraphs, pub_paragraphs, _match_by_length, _chapter_agreements(french, published)
    )
    if texts is None:
        return None

    report.method = "anchored"
    report.dropped += len(pub_paragraphs) - sum(1 for t in texts if t)
    report.unmatched = sum(1 for t in texts if not t)
    return {hash_text(p): text for p, text in zip(fr_paragraphs, texts)}


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
        method="pivot" if use_pivot else "proportional",
        chapters_matched=matched,
        total=sum(len(c.paragraphs) for c in fr_bodies),
    )
    aligned: dict[str, str] = {}

    # With no generated translation to pivot through, the editions are matched on
    # what survives translation: the names and numbers they share. That needs no
    # headings, so it carries books whose chapters are unmarked, unnumbered, or
    # written in a language this pipeline does not detect chapters in.
    if not use_pivot:
        anchored = _by_anchor(fr_bodies, pub_bodies, report)
        if anchored is not None:
            return anchored, report

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
            texts = _match_by_length(fr.paragraphs, pub.paragraphs)
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
