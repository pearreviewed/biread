"""A book that arrived with no paragraph breaks, cut to the shape of the other one.

A conversion can lose every paragraph mark — a PDF saved as a Word file comes
through as one run of four hundred thousand characters — and there is nothing
inside such a file to put the breaks back from. But where two editions of the
book are in play, the other one is a real edition, set by a publisher: how many
paragraphs the passage has and how long each runs is not ours and not a guess. It
is read off a copy of the book.

So the flattened side is cut to that shape. Each break is placed at the sentence
nearest the position the counterpart's own paragraph ends at, as a share of the
whole — the assumption sentence alignment has run on since Gale and Church, that
a paragraph holding a fifth of its book holds about a fifth of the other side's
too.

Two things make it work, and both were arrived at by measuring:

- **Absolute, not accumulated.** Each break is placed against the position it
  should fall at, never by pouring sentences in until a paragraph looks full.
  Pouring accumulates its error — one paragraph overshooting by a sentence pushes
  every later break along with it — and it recovered 3% of a book where placing
  absolutely recovers 69%.
- **Positions counted with the joining space.** Paragraphs and sentences divide
  the same text at different places, so a position measured without the spaces is
  short by however many boundaries it has passed, and that is not a constant:
  dialogue runs many short sentences to the page and narration few.

What this cannot do is find a break where no sentence ends — a heading, a line of
verse, a paragraph closing without a full stop, fuses with what follows. On a
real novel that is about a tenth of them.

What comes out says what it is. `AlignmentReport.cut` carries which side was cut,
and the reader is told in the ⓘ panel: a book whose paragraphing on one side came
off the other edition must say so.
"""
from __future__ import annotations

from .align import _sentences
from .cleanup import Chapter

#: A paragraph of prose runs to a few hundred characters, occasionally a couple of
#: thousand. A "paragraph" longer than this is a run of them fused together — the
#: file never came apart — which is the condition this module answers.
BLOCK_LIMIT = 6000


def unsegmented(chapters: list[Chapter]) -> bool:
    """Did this edition arrive without its paragraph breaks?"""
    paragraphs = [p for chapter in chapters for p in chapter.paragraphs]
    if not paragraphs:
        return False
    lengths = sorted(len(p) for p in paragraphs)
    return lengths[len(lengths) // 2] > BLOCK_LIMIT


def _ends(pieces: list[str]) -> list[int]:
    """Where each piece ends, in the text they make when joined by single spaces.

    The joining space is counted, and that is the point: it makes a paragraph
    position and a sentence position two readings of one ruler.
    """
    out, running = [], 0
    for piece in pieces:
        running += (len(piece) or 1) + 1
        out.append(running)
    return out


def _pieces_by(ends: list[int], position: float) -> int:
    """How many pieces are done by `position` characters in.

    A count, not an index, and the difference is the whole of it: a break falling
    exactly where a sentence ends belongs *after* that sentence. Counted the other
    way every break sits one sentence short, which is invisible in the arithmetic
    and cost two thirds of the paragraphs in a book.
    """
    lo, hi = 0, len(ends)
    while lo < hi:
        mid = (lo + hi) // 2
        if ends[mid] <= position:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _nearest(ends: list[int], position: float) -> int:
    """The sentence boundary closest to `position`, as a count of sentences.

    Nearest, not the next one past: a break sought at the exact character where a
    paragraph ends falls a hair beyond it as often as a hair before, and always
    rounding one way puts every second paragraph a sentence out.
    """
    at = _pieces_by(ends, position)
    if at >= len(ends):
        return len(ends)
    before = ends[at - 1] if at else 0
    return at if position - before <= ends[at] - position else at + 1


def segment_like(blob: list[Chapter], counterpart: list[Chapter]) -> list[Chapter]:
    """The flattened edition, cut into the paragraphs and chapters of the other.

    Returns the flattened text unchanged where there is nothing to cut it
    against, so a caller never has to ask whether it worked — `unsegmented` on the
    result still answers.
    """
    sentences = [s for chapter in blob for p in chapter.paragraphs for s in _sentences(p)]
    shape = [(index, p) for index, chapter in enumerate(counterpart)
             for p in chapter.paragraphs]
    if not sentences or not shape:
        return blob

    ends = _ends(sentences)
    wanted = _ends([p for _, p in shape])
    length, total = ends[-1], wanted[-1]

    cut = [Chapter(c.number, c.title, [], c.part) for c in counterpart]
    at = 0
    for index, (chapter, want) in enumerate(zip((i for i, _ in shape), wanted)):
        # The last paragraph takes whatever is left: the book must come out
        # whole, and rounding must not drop a sentence off the end of it.
        stop = len(sentences) if index == len(wanted) - 1 else _nearest(ends, want / total * length)
        stop = min(max(stop, at), len(sentences))
        if stop > at:
            # An empty draw means that paragraph pulled nothing — a paragraph
            # shorter than the sentence beside it — and this side simply has one
            # paragraph fewer there. What faces what is the aligner's decision.
            cut[chapter].paragraphs.append(" ".join(sentences[at:stop]))
        at = stop
    return [c for c in cut if c.paragraphs] or blob
