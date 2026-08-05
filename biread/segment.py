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

import re

from .align import _sentences
from .cleanup import Chapter

# Where a novel opens a line of speech, which is a paragraph break as surely as a
# full stop is and leaves no full stop behind it. Both halves are required, and
# that is what makes it corroboration rather than shape: a line that *introduces*
# speech, closing on a colon or a dash or a quotation, and then the mark that
# opens the speech itself. "…se tournant vers le maître d’études:" then "— Monsieur
# Roger…"; "…he said to him in a low voice—" then "“Monsieur Roger…". Between them
# these are 96% of what English Bovary loses and 91% of the French.
#
# A dash alone would not do: French sets a parenthesis with the same character
# ("il était — comment dire — fatigué"), and that one is preceded by a word.
#
# The space after the mark is optional and that is not a detail: English sets
# “Monsieur Roger with no gap and French sets — Monsieur Roger with one, and a
# pattern that demanded the word immediately fired on every English break and no
# French one at all — 98% against 79% of the same book in two languages.
SPEECH_RE = re.compile(r'(?<=[:;—–"”»])\s+(?=[—–«"“]\s*\S)')

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


def _pieces(text: str) -> list[str]:
    """Every place this text could plausibly have ended a paragraph.

    Sentence ends, and the openings of speech that leave none. Being generous
    here is close to free: the cut takes the candidate *nearest* the position a
    paragraph should end at, so an extra candidate is used only where it happens
    to be the best answer going. What it cannot do is invent a break where there
    is no mark at all — a chapter heading run into the prose behind it stays run
    into it.
    """
    return [piece for sentence in _sentences(text)
            for piece in SPEECH_RE.split(sentence) if piece.strip()]


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


#: How much text one break-finding call is shown. Small enough that the model
#: holds the whole passage in view, large enough that a book is tens of calls and
#: not thousands.
WINDOW_CHARS = 6000

#: The numbers come back one per paragraph, so the ceiling only has to clear the
#: paragraph count of one window.
MAX_TOKENS = 2000

BREAK_SYSTEM = (
    "You restore paragraph breaks to a book whose formatting was lost in "
    "conversion. You never rewrite, translate or comment on the text."
)

BREAK_PROMPT = (
    "Below are numbered pieces of a book. Each piece is one sentence or one line "
    "of speech, in order. The paragraph breaks were lost, so you cannot see them; "
    "your job is to say where they were.\n\n"
    "Reply with the numbers of the pieces that BEGIN a new paragraph — nothing "
    "else, no words, no punctuation but spaces between the numbers. Piece 1 begins "
    "one by definition; do not include it. A new speaker always begins a "
    "paragraph. So does a chapter heading, a date line, or a change of scene.\n\n"
    "{pieces}"
)


def _windows(pieces: list[str]) -> list[tuple[int, list[str]]]:
    """The pieces in runs of about `WINDOW_CHARS`, with where each run starts."""
    out, start, chars = [], 0, 0
    for index, piece in enumerate(pieces):
        if chars and chars + len(piece) > WINDOW_CHARS:
            out.append((start, pieces[start:index]))
            start, chars = index, 0
        chars += len(piece)
    if start < len(pieces):
        out.append((start, pieces[start:]))
    return out


def _openings(reply: str, count: int) -> list[int]:
    """The piece numbers the model gave back, as offsets into the window.

    Only what is usable survives: a number outside the window, or one that does
    not move forward, is dropped rather than trusted. The model is proposing
    positions in text it was shown; it is never quoted, so the worst a bad reply
    can do is put a break in an odd place, and the words on the page are the
    book's either way.
    """
    out: list[int] = []
    for token in re.findall(r"\d+", reply):
        at = int(token) - 1
        if 0 < at < count and (not out or at > out[-1]):
            out.append(at)
    return out


def repair_by_model(blob: list[Chapter], client, cfg=None) -> list[Chapter]:
    """Paragraph breaks for a flattened book with no other edition to take them from.

    The last resort, and only reached when nothing free can work: with a
    counterpart in hand `segment_like` is better, exact and costs nothing. Here
    there is no counterpart, so a model is asked to read the text and say where
    the paragraphs began.

    It is asked in the safest form there is. The text is cut into sentences
    first, and the model answers with the *numbers* of the pieces that open a
    paragraph — so it cannot rewrite a word even in principle, and a reply that
    is nonsense costs a badly placed break rather than a sentence of Voltaire.
    The same reasoning as glossing, one step further: there, the model's text is
    thrown away after anchoring; here it never has any.

    A window whose call fails is left unbroken rather than guessed, and the rest
    of the book still comes back.
    """
    pieces = [s for chapter in blob for p in chapter.paragraphs for s in _pieces(p)]
    if not pieces:
        return blob

    paragraphs: list[str] = []
    for start, window in _windows(pieces):
        numbered = "\n".join(f"{i + 1}. {piece}" for i, piece in enumerate(window))
        try:
            reply = client.complete(
                BREAK_SYSTEM, BREAK_PROMPT.format(pieces=numbered), MAX_TOKENS
            )
        except Exception:
            paragraphs.append(" ".join(window))
            continue
        cuts = [0] + _openings(reply.text, len(window)) + [len(window)]
        paragraphs.extend(" ".join(window[a:b]) for a, b in zip(cuts, cuts[1:]) if b > a)
    return [Chapter(None, None, paragraphs)] if paragraphs else blob


def segment_like(blob: list[Chapter], counterpart: list[Chapter]) -> list[Chapter]:
    """The flattened edition, cut into the paragraphs and chapters of the other.

    Returns the flattened text unchanged where there is nothing to cut it
    against, so a caller never has to ask whether it worked — `unsegmented` on the
    result still answers.
    """
    sentences = [s for chapter in blob for p in chapter.paragraphs for s in _pieces(p)]
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
