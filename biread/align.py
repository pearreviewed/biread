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

import re
from dataclasses import dataclass, field
from statistics import median
from typing import Callable

from .anchor import MIN_ANCHORS, agreements, align_by_anchors, longest_run
from .cleanup import Chapter
from .errors import AlignmentError
from .numbering import chapter_number, number_tokens
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
    #: Characters of the published edition as it arrived, and as it ended up on
    #: the page. Their ratio is what tells a condensed translation from a failed
    #: match — see `align_published` and `placed_share`.
    published_chars: int = 0
    placed_chars: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def placed_share(self) -> float | None:
        """How much of the English that exists actually landed. None if unknown."""
        if not self.published_chars:
            return None
        return self.placed_chars / self.published_chars

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


def prose_only(paragraphs: list[str]) -> list[str]:
    """The body, with the published edition's own notes left out."""
    return [p for p in paragraphs if not FOOTNOTE_RE.match(p)]


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


# One sentence ends and the next begins: closing punctuation, any quotes that
# ride on it, then space. Good enough to chop a run of prose into pieces to share
# out; it need not be linguistically perfect, only roughly even.
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?…])["»”’\')\]]*\s+')


def _sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _flow(weights: list[int], units: list[str]) -> list[str]:
    """Pour `units` into len(weights) groups, in order and contiguously, each
    group sized to its weight, and none left empty while units remain to fill it.

    This is what keeps the two columns from going lopsided: a French paragraph is
    never handed the whole of a chapter while its neighbours sit blank. Each unit
    joins the current group until that group has met its share of the total, with
    one unit always held back for every later group so the tail is never starved.
    """
    n = len(weights)
    if n == 0:
        return []
    if not units:
        return [""] * n
    total_w = sum(weights) or n
    total_u = sum(len(u) or 1 for u in units) or len(units)
    target = [w / total_w * total_u for w in weights]
    groups: list[list[str]] = [[] for _ in range(n)]
    here = 0
    filled = 0.0
    for seen, unit in enumerate(units):
        remaining = len(units) - seen
        # Hold one unit back for each group still ahead, so none ends up empty.
        if groups[here] and remaining <= n - 1 - here:
            here += 1
            filled = 0.0
        groups[here].append(unit)
        filled += len(unit) or 1
        while here < n - 1 and filled >= target[here] and remaining - 1 > n - 1 - here:
            here += 1
            filled = 0.0
    return [" ".join(g) for g in groups]


def _match_by_length(french: list[str], published: list[str]) -> list[str]:
    """Set the published text beside the French by shape, so the two columns fill
    together instead of one running blank beside a wall of the other.

    With no vocabulary or number to go on, the surest thing two editions of a
    passage still share is shape: a long paragraph translates long and a short
    one short. So a French paragraph holding a given fraction of its side's text
    (measured in characters) draws the published text holding that same fraction
    of theirs.

    A published side that arrived under-segmented — its paragraph breaks lost in
    extraction, so a whole chapter comes through as one or two blobs — is broken
    back into sentences first. Otherwise one blob would land whole on a single
    French paragraph and leave every neighbour empty, which is exactly the
    lopsided page a reader sees as "misaligned".
    """
    n, m = len(french), len(published)
    if n == 0:
        return []
    if m == 0:
        return [""] * n
    units = _sentences(" ".join(published)) if m < n else list(published)
    if len(units) <= n:
        return _distribute(french, units)
    return _flow([len(p) or 1 for p in french], units)


def _flow_spread(left: list[str], right: list[str]) -> list[str]:
    return _flow([len(x) or 1 for x in left], right)


# Gale & Church (1993): a sentence's translation runs about `ratio` times its
# length, and the cost of a proposed pairing is how far the lengths stray from
# that. 6.8 is their variance constant. The step set lets a sentence pair one to
# one, split into two, merge from two, or (rarely) drop or appear — enough to
# follow a translator who breaks one line of dialogue into two or fuses two.
_GALE_CHURCH_STEPS = ((1, 1, 0.0), (1, 2, 1.0), (2, 1, 1.0), (2, 2, 2.2), (1, 0, 3.0), (0, 1, 3.0))


def _shape_spread(left: list[str], right: list[str]) -> list[str]:
    """Fill a segment between two anchors by pairing sentences on length.

    A proportional pour keeps a segment the right size but slips where the two
    sides split their sentences differently — a run of terse dialogue, where the
    French sets each "—Oui." on its own line and the English fuses two into
    "Yes, I should like nothing better," has no name or number to pin it, so it
    drifts a line. Aligning by length instead (Gale & Church) pairs a short line
    with a short one and lets two lines meet one, which is exactly that case.
    """
    n, m = len(left), len(right)
    if n == 0:
        return []
    if m == 0:
        return [""] * n
    left_len = [len(s) or 1 for s in left]
    right_len = [len(s) or 1 for s in right]
    ratio = sum(right_len) / sum(left_len)

    def cost(li: int, lj: int) -> float:
        mean = li * ratio
        return (lj - mean) ** 2 / (mean * 6.8 or 1)

    inf = float("inf")
    best = [[inf] * (m + 1) for _ in range(n + 1)]
    step = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if best[i][j] == inf:
                continue
            for di, dj, penalty in _GALE_CHURCH_STEPS:
                if i + di > n or j + dj > m:
                    continue
                total = best[i][j] + cost(sum(left_len[i:i + di]) or 1, sum(right_len[j:j + dj]) or 1) + penalty
                if total < best[i + di][j + dj]:
                    best[i + di][j + dj] = total
                    step[i + di][j + dj] = (di, dj)

    beads: list[tuple[int, int, int, int]] = []
    i, j = n, m
    while (i, j) != (0, 0):
        di, dj = step[i][j]
        beads.append((i - di, i, j - dj, j))
        i, j = i - di, j - dj
    beads.reverse()

    out = [""] * n
    pending = ""  # a right sentence matched to no left one waits for the next bead
    for left_from, left_to, right_from, right_to in beads:
        text = " ".join(right[right_from:right_to])
        if left_from == left_to:
            pending = f"{pending} {text}".strip()
            continue
        out[left_from] = f"{pending} {text}".strip()
        pending = ""
    if pending:
        for k in range(n - 1, -1, -1):
            if out[k] or k == 0:
                out[k] = f"{out[k]} {pending}".strip()
                break
    return out


def _flow_anchored(french: list[str], published: list[str]) -> list[str]:
    """One published string per French paragraph, pinned on the names and numbers
    the two editions share so neither column drifts ahead of the other.

    A proportional split keeps the columns the same size but not the same place:
    with nothing holding them together the published text slides a sentence or
    two ahead of the French carrying the same name. So both sides are cut into
    sentences and anchored on the rare tokens they share — a proper noun, a number
    — which pins those sentences to each other; the sentences between two anchors
    are shared out by length, so the columns stay level and no paragraph is left
    blank. Each French paragraph's share is joined back beneath it.

    Falls back to the plain length-proportional fill when the chapter offers too
    few shared names to anchor on.
    """
    owners: list[int] = []
    fr_sentences: list[str] = []
    for index, paragraph in enumerate(french):
        for sentence in _sentences(paragraph):
            owners.append(index)
            fr_sentences.append(sentence)
    en_sentences = _sentences(" ".join(published))
    if len(fr_sentences) < MIN_ANCHORS or not en_sentences:
        return _match_by_length(french, published)

    # Names and cognates (shared folded prefixes) and every number read back to
    # its value, plus the chapter's own ends: a chapter begins and ends together
    # in both editions, so its first and last sentences anchor to each other too.
    proposed = agreements(fr_sentences, en_sentences, number_tokens)
    proposed += [(0, 0), (len(fr_sentences) - 1, len(en_sentences) - 1)]
    anchors = longest_run(proposed)
    if len(anchors) < MIN_ANCHORS:
        return _match_by_length(french, published)

    # Each anchor opens a fresh segment on both sides; the sentences within it are
    # poured by length, so an anchored name keeps its two editions level.
    assigned = [""] * len(fr_sentences)
    fr_prev = en_prev = 0
    for fr_at, en_at in list(anchors) + [(len(fr_sentences), len(en_sentences))]:
        if fr_at > fr_prev:
            assigned[fr_prev:fr_at] = _shape_spread(
                fr_sentences[fr_prev:fr_at], en_sentences[en_prev:en_at]
            )
        fr_prev, en_prev = fr_at, en_at

    buckets: list[list[str]] = [[] for _ in french]
    for text, owner in zip(assigned, owners):
        if text:
            buckets[owner].append(text)
    result = [" ".join(b) for b in buckets]
    # A paragraph the anchors happen to leave empty still takes its proportional
    # share, so the column never runs blank beside a full one.
    if not all(result):
        proportional = _match_by_length(french, published)
        result = [got or share for got, share in zip(result, proportional)]
    return result


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


# The heading a scholarly edition sets over its back matter — a bibliography, a
# run of endnotes, an index. Matched only as a paragraph that *is* the heading and
# nothing else, so a chapter that merely mentions notes or an index in a sentence
# is untouched.
BACK_MATTER_HEADINGS = frozenset({
    "bibliographie", "bibliography", "notes", "index", "appendix", "appendice",
    "appendices", "glossaire", "glossary", "works cited", "œuvres citées",
    "oeuvres citées", "table des matières", "abbreviations", "abréviations",
    "chronologie", "chronology",
})


def _is_back_matter_heading(paragraph: str) -> bool:
    return paragraph.strip().rstrip(".").lower() in BACK_MATTER_HEADINGS


def _strip_trailing_matter(chapters: list[Chapter]) -> list[Chapter]:
    """Cut a scholarly apparatus that trails the last chapter — a bibliography,
    endnotes, an index — which an academic edition appends after the book ends and
    the other edition has no counterpart for. It announces itself with a heading of
    its own ("BIBLIOGRAPHIE"); everything from there to the end goes.

    Only the back half of the book is examined, since apparatus follows the text
    and never precedes its midpoint — so a chapter early on cannot be cut short.
    """
    for index in range(len(chapters) // 2, len(chapters)):
        chapter = chapters[index]
        for position, paragraph in enumerate(chapter.paragraphs):
            if _is_back_matter_heading(paragraph):
                kept = list(chapters[:index])
                if position:
                    kept.append(Chapter(chapter.number, chapter.title, chapter.paragraphs[:position]))
                return kept or chapters
    return chapters


def trim_matter(chapters: list[Chapter]) -> list[Chapter]:
    """Drop what brackets a book without being the book: a title page, a table of
    contents, a publisher's notice or a critic's introduction in front; a licence,
    a bibliography or an index behind. These are exactly the sections cleanup
    could not number.

    Leaving them in is what puts two editions permanently out of step — one
    edition's forty-page introduction would otherwise shift every paragraph after
    it. Where chapters are numbered, everything outside the numbered run goes, and
    any apparatus that trails inside the last chapter is cut too. Where none are,
    the book is not left untouched but combed for the boilerplate that opens a
    file — so it still starts on real text, or on a named front section, rather
    than on "Produced by …".
    """
    numbered = [i for i, c in enumerate(chapters) if chapter_number(c.number) is not None]
    if not numbered:
        return _strip_leading_matter(chapters)
    return _strip_trailing_matter(chapters[numbered[0] : numbered[-1] + 1])


def _key(chapter: Chapter) -> tuple[int | None, int | None]:
    """What names a chapter across two editions: its number, and the part it is
    numbered within where the book has parts."""
    return (chapter.part, chapter_number(chapter.number))


def _pair_by_number(french: list[Chapter], published: list[Chapter]):
    """Pair chapters on the number they carry rather than the order they arrive
    in, so an extra preface on one side cannot shift the book. A French chapter
    with no counterpart pairs with None and is left blank rather than guessed."""
    by_number: dict[tuple[int | None, int | None], Chapter] = {}
    for chapter in published:
        key = _key(chapter)
        if key[1] is not None and key not in by_number:
            by_number[key] = chapter
    return [(c, by_number.get(_key(c))) for c in french]


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
    pub_paragraphs = prose_only([p for c in published for p in c.paragraphs])
    texts = align_by_anchors(
        fr_paragraphs, pub_paragraphs, _match_by_length, _chapter_agreements(french, published)
    )
    if texts is None:
        return None

    report.method = "anchored"
    report.dropped += len(pub_paragraphs) - sum(1 for t in texts if t)
    report.unmatched = sum(1 for t in texts if not t)
    return {hash_text(p): text for p, text in zip(fr_paragraphs, texts)}


def _by_chapter_balanced(
    french: list[Chapter], published: list[Chapter], report: AlignmentReport
) -> dict[str, str]:
    """The free path when both editions number their chapters: pair on the
    number, then fill each chapter's published text across its French by shape so
    the two columns stay full and advance together.

    This is what a reader means by "aligned" without a model in play — not a
    paragraph-perfect match, which two independently typeset editions cannot give,
    but two pages that fill and turn together, drifting at most within one chapter
    and never leaving one side blank against a wall of the other. A chapter the
    published edition simply does not carry is left blank rather than guessed.
    """
    report.method = "anchored"
    aligned: dict[str, str] = {}
    for index, (fr, pub) in enumerate(_pair_by_number(french, published)):
        if pub is None:
            report.unmatched += len(fr.paragraphs)
            report.notes.append(
                f"{_label(fr, index)}: the published edition has no chapter of that "
                f"number, so it is left blank rather than filled with a guess."
            )
            for paragraph in fr.paragraphs:
                aligned[hash_text(paragraph)] = ""
            continue
        # The chapter's argument (its descriptive heading) is set beside its
        # French counterpart, so both editions open the chapter on the same line
        # instead of the French heading facing the English body.
        if fr.title and pub.title:
            aligned[hash_text(fr.title)] = pub.title
        prose = prose_only(pub.paragraphs)
        report.dropped += len(pub.paragraphs) - len(prose)
        texts = _flow_anchored(fr.paragraphs, prose)
        blank = sum(1 for t in texts if not t)
        report.unmatched += blank
        if len(fr.paragraphs) == len(prose) and not blank:
            report.exact += 1
        else:
            report.grouped += 1
            if len(prose) < len(fr.paragraphs):
                report.notes.append(
                    f"{_label(fr, index)}: the published edition arrived with its "
                    f"paragraph breaks lost ({len(prose)} block(s) for "
                    f"{len(fr.paragraphs)} French paragraph(s)), so its text is shared "
                    f"out across the French by length."
                )
        for paragraph, text in zip(fr.paragraphs, texts):
            aligned[hash_text(paragraph)] = text
    return aligned


#: French paragraphs -> the published paragraph each is closest to, need a shared
#: semantic space. A multilingual embedding model (BGE-M3 local, or a cloud one)
#: gives it: a French sentence and its English translation land near each other
#: even sharing no words. `embed(texts) -> one vector per text`.
Embed = Callable[[list[str]], list[list[float]]]


def _unit(v: list[float]) -> list[float]:
    scale = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / scale for x in v]


def _embedding_pivot(
    french: list[str], published: list[str],
    fr_vecs: list[list[float]], pub_vecs: list[list[float]],
) -> list[str]:
    """One published string per French paragraph, each published paragraph given to
    the French it is nearest in meaning (embedding cosine), in reading order.

    The two editions run in the same order, so this is a monotonic many-to-one
    matching — the same dynamic program the generated-translation pivot uses, but
    scored by cosine similarity across a shared multilingual space instead of by
    shared English words. That is what lets it match "—Quand ?" to "When?", which
    have no character in common."""
    n, m = len(french), len(published)
    if not n:
        return []
    if not m:
        return [""] * n

    fr = [_unit(v) for v in fr_vecs]
    pub = [_unit(v) for v in pub_vecs]

    NEG = float("-inf")
    best = [[NEG] * (n + 1) for _ in range(m + 1)]
    best[0] = [0.0] * (n + 1)
    for i in range(1, m + 1):
        row, previous, vec = best[i], best[i - 1], pub[i - 1]
        for j in range(1, n + 1):
            stay = previous[j] + sum(a * b for a, b in zip(vec, fr[j - 1]))
            advance = row[j - 1]
            row[j] = stay if stay > advance else advance

    groups: list[list[str]] = [[] for _ in range(n)]
    i, j = m, n
    while i > 0 and j > 0:
        if best[i][j] == best[i][j - 1]:
            j -= 1
            continue
        groups[j - 1].append(published[i - 1])
        i -= 1
    return [" ".join(reversed(g)) for g in groups]


def embed_match(french: list[str], published: list[str], embed: Embed) -> list[str]:
    """One published string per French paragraph, matched by meaning.

    Guarding the empty cases here keeps `embed` from being called with nothing to
    embed, which some providers refuse outright.
    """
    if not french:
        return []
    if not published:
        return [""] * len(french)
    return _embedding_pivot(french, published, embed(french), embed(published))


#: How far a paragraph's best match must stand above the window's typical score
#: before it counts as the same passage rather than merely more prose. Judged
#: against the window's own median, not an absolute cosine, because each embedding
#: model scores on its own scale and a number tuned to one would quietly blank
#: every page on another. Measured on Micromégas against text-embedding-3-large:
#: true pairs stand .43–.56 above the median, wrong ones .28–.31.
NEAREST_MARGIN = 0.38


def embed_nearest(
    french: list[str], published: list[str], embed: Embed, margin: float = NEAREST_MARGIN
) -> list[str]:
    """The published paragraph nearest each French one, or nothing where none stands out.

    For a window rather than a whole book. `_embedding_pivot` must place *every*
    published paragraph somewhere, which is right when the two lists cover the same
    span and badly wrong when the window runs twenty times the length of the page —
    it hands the whole window out among three paragraphs instead of finding the
    three that answer to them. Here each French paragraph takes the one match that
    rises clearly above the rest, or none; and matches only move forward, because
    two editions run in the same order.
    """
    if not french:
        return []
    if not published:
        return [""] * len(french)
    fr = [_unit(v) for v in embed(french)]
    pub = [_unit(v) for v in embed(published)]

    out: list[str] = []
    start = 0
    for vec in fr:
        scores = [sum(a * b for a, b in zip(vec, p)) for p in pub]
        typical = median(scores)
        at = max(range(start, len(scores)), key=scores.__getitem__, default=None)
        if at is None or scores[at] - typical < margin:
            out.append("")
            continue
        out.append(published[at])
        start = at + 1
    return out


#: How much of the French must find a numbered counterpart before the two
#: editions are taken to be divided the same way.
NUMBERING_AGREES = 0.8


def _chapter_gist(chapter: Chapter) -> str:
    """Enough of a chapter to recognise it by. Its opening prose, several
    paragraphs of it, so a stray heading left in the body cannot be the whole
    signal."""
    return " ".join(prose_only(chapter.paragraphs)[:3])[:1200]


#: How many of the numbered pairings may look wrong before the numbering itself
#: is disbelieved. Generous, because a translation genuinely rewrites and two
#: adjacent chapters can read alike; a shift by one fails on nearly all of them.
NUMBERING_MISMATCH = 0.25


def _chapter_vectors(
    french: list[Chapter], published: list[Chapter], embed: Embed
) -> tuple[list[list[float]], list[list[float]]]:
    """One vector per chapter a side. Two embedding calls for a whole book."""
    return ([_unit(v) for v in embed([_chapter_gist(c) for c in french])],
            [_unit(v) for v in embed([_chapter_gist(c) for c in published])])


def _pair_by_content(
    french: list[Chapter], published: list[Chapter],
    fr_vecs: list[list[float]], pub_vecs: list[list[float]],
) -> list[tuple[Chapter, Chapter | None]]:
    """Pair chapters by what they are about, in order, letting either side skip.

    The same monotonic matching the paragraphs get, run over whole chapters — a
    47-by-46 problem rather than a 3,404-by-2,140 one, which is why the answer to
    untrustworthy numbering is to re-derive the chapters rather than to throw the
    chapter structure away: the whole-book path cannot carry a book this size.
    A French chapter the translation genuinely lacks pairs with None and is left
    blank, which is what an omitted chapter deserves.
    """
    n, m = len(fr_vecs), len(pub_vecs)
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            similarity = sum(a * b for a, b in zip(fr_vecs[i - 1], pub_vecs[j - 1]))
            best[i][j] = max(best[i - 1][j], best[i][j - 1],
                             best[i - 1][j - 1] + similarity)

    partner: dict[int, int] = {}
    i, j = n, m
    while i > 0 and j > 0:
        similarity = sum(a * b for a, b in zip(fr_vecs[i - 1], pub_vecs[j - 1]))
        if best[i][j] == best[i - 1][j - 1] + similarity:
            partner[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif best[i][j] == best[i - 1][j]:
            i -= 1
        else:
            j -= 1
    return [(c, published[partner[k]] if k in partner else None)
            for k, c in enumerate(french)]


def _numbering_holds(
    published: list[Chapter], pairs: list[tuple[Chapter, Chapter | None]],
    fr_vecs: list[list[float]], pub_vecs: list[list[float]],
) -> bool:
    """Do the chapters the numbers paired actually correspond?

    A translation that drops a chapter and renumbers what follows leaves both
    editions carrying contiguous, complete-looking numbers, with every later
    pairing off by one. There is no gap to find and no count to compare — the
    1911 Twenty Thousand Leagues omits French XI and renumbers, so 46 of 47
    chapters "matched" and 37 of them were the wrong chapter.

    Nothing structural can see that. Only the text can: a chapter is checked
    against the one its number chose and against that one's neighbours, and if
    a neighbour is the better read of it, the numbering is not to be trusted.
    """
    place = {id(c): i for i, c in enumerate(published)}
    checkable = [(i, place[id(pub)]) for i, (_, pub) in enumerate(pairs) if pub is not None]
    if len(checkable) < 4:
        return True

    def score(i: int, j: int) -> float:
        return sum(a * b for a, b in zip(fr_vecs[i], pub_vecs[j]))

    wrong = 0
    for i, j in checkable:
        neighbours = [k for k in (j - 1, j + 1) if 0 <= k < len(pub_vecs)]
        if any(score(i, k) > score(i, j) for k in neighbours):
            wrong += 1
    return wrong <= len(checkable) * NUMBERING_MISMATCH


def _chapter_pairs(
    french: list[Chapter], published: list[Chapter], embed: Embed | None = None
) -> list[tuple[Chapter, Chapter | None]]:
    """Chapter against chapter where the two editions divide the book alike, and
    the whole book against the whole book where they do not.

    Chapter numbers are only worth pairing on when they actually correspond. An
    edition that merges thirty chapters into twenty-five carries numbers that look
    pairable and are not: the tail of the French finds no counterpart and is left
    blank, though every word of it is present in the other book under a different
    number. Six French chapters against three merged English ones cover 50% paired
    this way, and 100% run whole — so where the numbering does not agree, the
    numbering is the thing to discard.
    """
    pairs = _pair_by_number(french, published)
    matched = sum(1 for _, pub in pairs if pub is not None)
    if matched >= 2 and matched >= len(pairs) * NUMBERING_AGREES:
        if embed is None:
            return pairs
        fr_vecs, pub_vecs = _chapter_vectors(french, published, embed)
        if _numbering_holds(published, pairs, fr_vecs, pub_vecs):
            return pairs
        return _pair_by_content(french, published, fr_vecs, pub_vecs)
    return [(
        Chapter(None, None, [p for c in french for p in c.paragraphs]),
        Chapter(None, None, [p for c in published for p in c.paragraphs]),
    )]


def _by_embeddings(
    french: list[Chapter], published: list[Chapter], embed: Embed, report: AlignmentReport,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, str]:
    """Match two editions in a shared semantic space — the trustworthy no-key path.

    Chapters pair on the number they carry (else the whole book is one run); within
    each, French and published paragraphs are embedded and matched by cosine, so the
    columns line up by meaning rather than by the sparse words two languages share.
    `progress(done, total)` is called per chapter, so a long book is not silent while
    it embeds."""
    report.method = "pivot"
    pairs = _chapter_pairs(french, published, embed)
    aligned: dict[str, str] = {}
    for index, (fr, pub) in enumerate(pairs):
        if progress:
            progress(index, len(pairs))
        if pub is None or not fr.paragraphs:
            report.unmatched += len(fr.paragraphs)
            for paragraph in fr.paragraphs:
                aligned[hash_text(paragraph)] = ""
            continue
        prose = prose_only(pub.paragraphs)
        report.dropped += len(pub.paragraphs) - len(prose)
        texts = embed_match(fr.paragraphs, prose, embed)
        report.unmatched += sum(1 for t in texts if not t)
        report.exact += 1
        for paragraph, text in zip(fr.paragraphs, texts):
            aligned[hash_text(paragraph)] = text
    if progress:
        progress(len(pairs), len(pairs))
    return aligned


def align_published(
    french: list[Chapter],
    published: list[Chapter],
    translations: dict[str, str] | None = None,
    embed: Embed | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[dict[str, str], AlignmentReport]:
    """Map French paragraph hash -> published English text.

    Wraps the matching to weigh what landed against what there was. A coverage
    figure alone cannot tell a translator who condensed from an aligner that lost
    its way: 20,000 Leagues leaves 41% of the French facing nothing and is
    matched about as well as it can be, because the 1911 English *is* two-thirds
    of the French. The same 59% with a tenth of the English placed would be a
    fault. Only this ratio separates them.
    """
    aligned, report = _align_published(french, published, translations, embed, on_progress)
    report.published_chars = sum(len(p) for c in published for p in c.paragraphs)
    # Distinct text: where one English paragraph faces several French ones it is
    # the same English twice, and summing it twice would report more of the
    # edition on the page than the edition contains.
    report.placed_chars = sum(len(text) for text in set(aligned.values()))
    return aligned, report


def _align_published(
    french: list[Chapter],
    published: list[Chapter],
    translations: dict[str, str] | None = None,
    embed: Embed | None = None,
    on_progress: Callable[[int, int], None] | None = None,
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

    # Best when it is on offer: a shared multilingual embedding space (BGE-M3 run
    # locally, or a cloud model) matches the two editions by meaning, so the columns
    # line up even where they share no words at all.
    if embed is not None:
        return _by_embeddings(fr_bodies, pub_bodies, embed, report, on_progress), report

    # With no generated translation to pivot through, the editions are matched on
    # what survives translation: the names and numbers they share.
    if not use_pivot:
        # When both editions number their chapters, pair on the number and fill
        # each chapter so the two columns stay balanced (`_by_chapter_balanced`).
        # This is preferred over paragraph anchoring because anchoring pins a few
        # paragraphs and leaves the rest to a spread that goes lopsided when one
        # edition is under-segmented — the very failure that reads as "misaligned".
        if by_number:
            return _by_chapter_balanced(fr_bodies, pub_bodies, report), report
        # No shared chapter numbers: anchor on names/numbers instead. That needs
        # no headings, so it carries books whose chapters are unmarked or unnumbered.
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
            prose = prose_only(pub.paragraphs)
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
