"""Anchor two editions of one book to each other, with no model and no structure.

Two translations share almost no words — that is what makes cross-language
alignment hard, and why matching on vocabulary fails. But a handful of tokens
survive translation nearly intact: proper nouns (Candide, Pangloss,
Westphalie/Westphalia) and numbers (1755). A token that is *rare in both*
editions and present in both is therefore strong evidence that the two
paragraphs carrying it are the same passage.

Collect those agreements, keep the longest run of them that advances through
both books at once, and you have a skeleton to align against. Everything falls
out of it:

- **Front matter needs no special case.** If one edition opens with forty pages
  of a critic's introduction, its first anchor simply sits deep inside the file;
  everything before falls outside the skeleton and is never shown.
- **A missing or added chapter shifts nothing**, because the next anchor
  re-synchronises the two books.
- **No headings are required**, so a book whose sections are named, numbered
  "I.", or not marked at all aligns as readily as one that says CHAPITRE.

Chapter headings, where they exist, are not a separate code path: they are fed
in as extra anchors, being the most reliable agreement of all.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Callable, Sequence

#: Words of three letters or more, and runs of two digits or more. Single
#: letters and lone digits carry no evidence.
TOKEN_RE = re.compile(r"[^\W\d_]{3,}|\d{2,}", re.UNICODE)

#: Compared on a prefix, so an edition's spelling of a name need not match the
#: other's exactly: Westphalie/Westphalia and Lisbonne/Lisbon still agree.
PREFIX = 6

#: A token appearing all over a book says nothing about *which* paragraph is
#: which. Only tokens confined to a few paragraphs in both editions are
#: evidence, and a token must appear the same number of times in each before its
#: occurrences can be paired off in order.
MAX_OCCURRENCES = 3

#: Below this, the agreements are as likely to be coincidence as correspondence,
#: and the caller should fall back to something cruder rather than trust them.
MIN_ANCHORS = 4

#: A translator merges two paragraphs into one often enough. Six into one is not
#: a merge but material this edition does not carry, and a blank admits that,
#: where repeating one sentence down the page would only look broken.
MAX_MERGE = 2


def _share(left: list[str], right: list[str], spread) -> list[str]:
    """Place the paragraphs lying between two anchors."""
    if not right:
        return [""] * len(left)
    if len(left) <= len(right) * MAX_MERGE:
        return spread(left, right)
    # Far too little on the right to cover the left: an abridged or incomplete
    # edition. Put what there is where it belongs, and leave the rest blank.
    out = [""] * len(left)
    for index, text in enumerate(right):
        middle = (2 * index + 1) * len(left) // (2 * len(right))
        out[min(middle, len(left) - 1)] = text
    return out


def fold(word: str) -> str:
    """A token reduced to what survives translation: no accents, no case, and
    only its opening letters."""
    plain = unicodedata.normalize("NFKD", word).encode("ascii", "ignore").decode()
    return plain.lower()[:PREFIX]


def _positions(paragraphs: Sequence[str]) -> dict[str, list[int]]:
    """Folded token -> the paragraphs it appears in, in order, without repeats."""
    seen: dict[str, list[int]] = defaultdict(list)
    for index, paragraph in enumerate(paragraphs):
        for token in {fold(t) for t in TOKEN_RE.findall(paragraph)}:
            if len(token) >= 4:
                seen[token].append(index)
    return seen


def agreements(left: Sequence[str], right: Sequence[str]) -> list[tuple[int, int]]:
    """Paragraph pairs proposed by tokens rare in both editions.

    A token kept here is one that both books use sparingly and the same number
    of times, so its occurrences can be paired off in order. That is nearly
    always a name, a place or a number — the things a translator carries across
    rather than translates.
    """
    here, there = _positions(left), _positions(right)
    pairs: set[tuple[int, int]] = set()
    for token, mine in here.items():
        yours = there.get(token)
        if not yours or len(mine) != len(yours) or len(mine) > MAX_OCCURRENCES:
            continue
        pairs.update(zip(mine, yours))
    return sorted(pairs)


def longest_run(pairs: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """The longest subset of pairs that advances through both books at once.

    Two editions of a book run in the same order, so a genuine set of anchors
    never goes backwards on either side. Coincidental agreements, a name that
    happens to recur in an appendix, do not fit that run and are dropped.

    The run is non-decreasing rather than strictly increasing, because a
    translator is free to merge two paragraphs into one: both halves then anchor
    to the same paragraph, and demanding strict increase would throw one of them
    away and shift everything after it.
    """
    if not pairs:
        return []
    ordered = sorted(pairs)  # by left index, then right
    tails: list[int] = []       # tails[k]: smallest right-index ending a run of k+1
    where: list[int] = []       # index into `ordered` of each tail
    previous = [-1] * len(ordered)
    for position, (_left, right) in enumerate(ordered):
        low, high = 0, len(tails)
        while low < high:  # first tail past `right`, so the run never goes backwards
            middle = (low + high) // 2
            if tails[middle] <= right:
                low = middle + 1
            else:
                high = middle
        if low:
            previous[position] = where[low - 1]
        if low == len(tails):
            tails.append(right)
            where.append(position)
        else:
            tails[low] = right
            where[low] = position

    run, step = [], where[-1]
    while step != -1:
        run.append(ordered[step])
        step = previous[step]
    return run[::-1]


def align_by_anchors(
    left: Sequence[str],
    right: Sequence[str],
    spread: Callable[[list[str], list[str]], list[str]],
    extra: Sequence[tuple[int, int]] = (),
) -> list[str] | None:
    """One right-hand text per left-hand paragraph, or None if unanchorable.

    `extra` carries agreements the caller already knows — matching chapter
    numbers, say — which join the same run as everything else. `spread` places
    paragraphs inside a segment once its ends are pinned.

    None means the two files did not agree often enough to be trusted; the
    caller should say so rather than present a guess as an alignment.
    """
    anchors = longest_run(list(agreements(left, right)) + list(extra))
    if len(anchors) < MIN_ANCHORS:
        return None

    out = [""] * len(left)
    # An anchor pins one paragraph to one other. Two paragraphs pinned to the
    # same one are a merge, and both should show it; one paragraph pinned to
    # two is a split, and shows them joined.
    pinned: dict[int, list[int]] = defaultdict(list)
    for here, there in anchors:
        pinned[here].append(there)
    for here, theirs in pinned.items():
        out[here] = " ".join(right[t] for t in sorted(set(theirs)))

    # What lies between two pins is shared out between them, so a translator's
    # split or merge stays inside the gap where it happened instead of pushing
    # the rest of the book out of step.
    for (left_from, right_from), (left_to, right_to) in zip(anchors, anchors[1:]):
        if left_to <= left_from + 1:
            continue
        between = list(right[right_from + 1 : right_to])
        if not between and left_to - left_from - 1 <= MAX_MERGE:
            # The two pins meet on the right, so what lies between them was
            # merged into the paragraph the next pin names: show it there too.
            for index in range(left_from + 1, left_to):
                out[index] = right[right_to]
            continue
        out[left_from + 1 : left_to] = _share(
            list(left[left_from + 1 : left_to]), between, spread
        )

    # Before the first pin and after the last, take only as much as the left book
    # can use: an introduction or a licence outside the anchors is left behind.
    first, last = anchors[0], anchors[-1]
    if first[0]:
        out[: first[0]] = _share(
            list(left[: first[0]]),
            list(right[max(0, first[1] - first[0]) : first[1]]),
            spread,
        )
    if last[0] + 1 < len(left):
        room = len(left) - last[0] - 1
        out[last[0] + 1 :] = _share(
            list(left[last[0] + 1 :]),
            list(right[last[1] + 1 : min(len(right), last[1] + 1 + room)]),
            spread,
        )
    return out
