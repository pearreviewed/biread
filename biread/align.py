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

Without a generated translation to pivot on, this falls back to distributing
proportionally within each chapter, which is only a rough approximation.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cleanup import Chapter
from .errors import AlignmentError
from .translate import hash_text

# Digits included on purpose: dates, editions and quantities are among the
# most discriminating tokens a paragraph has.
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
# A published edition sets its notes as ordinary paragraphs; the source has no
# counterpart for them, so they are apparatus and never a translation of anything.
FOOTNOTE_RE = re.compile(r"^\[\d+\]")
MIN_SIMILARITY = 0.34  # a third of the shorter text must be shared to count
MIN_SHARED_WORDS = 2   # one word in common is coincidence, not correspondence

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


def _label(chapter: Chapter, index: int) -> str:
    if chapter.number:
        return f"Chapitre {chapter.number}"
    return "Opening section" if index == 0 else f"Section {index + 1}"


def align_published(
    french: list[Chapter],
    published: list[Chapter],
    translations: dict[str, str] | None = None,
) -> tuple[dict[str, str], AlignmentReport]:
    """Map French paragraph hash -> published English text.

    Pass `translations` (French hash -> generated English) to align by
    similarity, which is what makes the result trustworthy.
    """
    fr_bodies = [c for c in french if c.paragraphs]
    pub_bodies = [c for c in published if c.paragraphs]

    if not fr_bodies:
        raise AlignmentError("the French text has no paragraphs to align against.")
    if not pub_bodies:
        raise AlignmentError("the published translation has no paragraphs.")

    matched = len(fr_bodies) == len(pub_bodies)
    use_pivot = bool(translations)
    report = AlignmentReport(
        method="pivot" if use_pivot else "proportional", chapters_matched=matched
    )
    aligned: dict[str, str] = {}

    # Chapters are the one boundary translators keep, so align within them when
    # the structure agrees; otherwise treat the book as one run.
    if matched:
        pairs = list(zip(fr_bodies, pub_bodies))
    else:
        pairs = [(
            Chapter(None, None, [p for c in fr_bodies for p in c.paragraphs]),
            Chapter(None, None, [p for c in pub_bodies for p in c.paragraphs]),
        )]
        report.notes.append(
            f"Chapter structures differ ({len(fr_bodies)} French vs {len(pub_bodies)} "
            f"published) — aligned across the whole book instead of per chapter."
        )

    for index, (fr, pub) in enumerate(pairs):
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
            texts = _distribute(fr.paragraphs, pub.paragraphs)
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
