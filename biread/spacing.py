"""Words an OCR ran together, put back apart without one of them being rewritten.

A scan stores an image of every page and the characters read off it, and the
reading is imperfect in a particular way: spaces go missing. `isvery small and
clean`, `the firstsheet is undated`, `TranslatedfromtheFrenchby`. On the Internet
Archive Nausea, 1.9% of the English words appear nowhere in the same translation
digitally typeset, and 835 of those are two real words run together.

Everything else here refuses to let a model write into a book, and that refusal
is not relaxed here either. What is kept from a reply is not its text:

    only where it put the spaces

The reply is read character by character against the original, and the passage is
rebuilt from **the original's own characters** with the model's spacing. So the
model's text never reaches the page at all, exactly as in glossing, where only
offsets survive. A reply that rewrites a word, drops a clause, translates a line
or answers with an apology stops aligning and is discarded whole.

The one thing a model may differ in without being disbelieved is the *shape* of a
quotation mark, and it costs nothing to allow because the mark that goes on the
page is ours regardless. It was worth finding: asked to respace real passages of
the Nausea scan, Sonnet spaced them correctly and straightened `’` to `'` in half
of them, and a rule about the reply's own characters threw those repairs away
over an apostrophe.

Two passes, in the order that keeps it cheap. The free one finds candidates, by
corroboration rather than by shape — a word the book itself never uses, whose
halves the book uses constantly, has been run together. That rule cannot be
trusted to *act*: measured on a real scan it proposed 505 splits of which 208
were wrong, taking real words apart (`notebooks`, `otherwise`, `reasonable`),
because nothing about a word's shape distinguishes `notebooks` from `firstsheet`.
It is a fine filter, though, and the model adjudicates what it finds. So the free
rule proposes, the model disposes, and the verification means neither of them can
damage a sentence.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .cleanup import Chapter

#: A word is trusted when the book uses it on its own this often. Three, because
#: an OCR join is usually a one-off and a real word of a novel is not.
TRUSTED_AT = 3

#: Shorter than this and a split is as likely to be noise as a repair.
LONGEST_SAFE = 6

WORD = re.compile(r"[^\W\d_]{2,}", re.UNICODE)

MAX_TOKENS = 2000

SPACING_SYSTEM = (
    "You repair the spacing of text read off a scanned page. You never rewrite, "
    "translate, correct, complete or comment on it. Only spaces may change."
)

SPACING_PROMPT = (
    "The passage below was read off a photograph of a printed page, and the "
    "reading lost some of the spaces between words: `isvery` for `is very`, "
    "`thefirst` for `the first`. Some may also have gained one in the middle of "
    "a word.\n\n"
    "Reply with the same passage, spaced correctly, and with nothing else "
    "changed. Every letter, digit, accent and mark must come back exactly as it "
    "is and in the same order, including anything that looks like a misreading: "
    "a misread word is the file's, and not yours to fix. Add no commentary and "
    "no quotation marks of your own. If the spacing is already right, reply with "
    "the passage unchanged.\n\n"
    "{passage}"
)


@dataclass
class RespaceRun:
    """What a respacing pass did, in the terms the terminal reports."""
    looked_at: int = 0
    #: Passages the model changed and the check accepted.
    repaired: int = 0
    #: Replies thrown away because they were not the same text.
    refused: int = 0
    #: Calls that failed outright; those passages are left as the file had them.
    failed: int = 0
    #: A few of the words that came apart, so the terminal can show its work.
    words: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.repaired)


def letters(text: str) -> str:
    """The passage with every space taken out: what may not change."""
    return "".join(text.split())


#: Marks a model may render differently without being disbelieved. Only the shape
#: of a quotation mark, and only because what goes on the page is ours anyway.
QUOTEISH = set("'\u2018\u2019\u201c\u201d\u00ab\u00bb\"`\u00b4")


def respaced(original: str, reply: str) -> str | None:
    """The original's own characters, carrying the model's spacing. None if the
    reply is not the same passage.

    This function is the whole safety argument, and it is deliberately dull. It
    walks the reply against the original one character at a time and writes out
    **the original's** character each time, so nothing the model typed is on the
    page even when the reply is perfect. A character that does not answer to
    ours ends the whole passage rather than being skipped: a model that mends a
    misreading, drops a clause or adds a word of its own stops aligning at that
    point, and the passage is left as the file had it.
    """
    ours = [c for c in original if not c.isspace()]
    out: list[str] = []
    at = 0
    for char in reply.strip():
        if char.isspace():
            if out and out[-1] != " ":
                out.append(" ")
            continue
        if at >= len(ours):
            return None
        if char != ours[at] and not (char in QUOTEISH and ours[at] in QUOTEISH):
            return None
        out.append(ours[at])
        at += 1
    if at != len(ours):
        return None
    candidate = "".join(out).strip()
    return candidate if candidate != original else None


def _trusted(paragraphs: list[str]) -> set[str]:
    counts = Counter(w.lower() for p in paragraphs for w in WORD.findall(p))
    return {w for w, n in counts.items() if n >= TRUSTED_AT}


def run_together(paragraphs: list[str]) -> list[str]:
    """The words this book appears to have run together, by its own evidence.

    A word the book never settles on, whose halves it uses constantly, is one
    word too few. Proposals only: `notebooks` answers this description as well
    as `firstsheet` does, which is exactly why nothing here acts on it.
    """
    trusted = _trusted(paragraphs)
    seen: dict[str, None] = {}
    for paragraph in paragraphs:
        for word in WORD.findall(paragraph):
            low = word.lower()
            if len(low) < LONGEST_SAFE or low in trusted or low in seen:
                continue
            if any(low[:i] in trusted and low[i:] in trusted for i in range(2, len(low) - 1)):
                seen[low] = None
    return list(seen)


def suspect(paragraphs: list[str]) -> list[int]:
    """Which paragraphs are worth paying to look at: those carrying a candidate."""
    joins = set(run_together(paragraphs))
    if not joins:
        return []
    return [i for i, p in enumerate(paragraphs)
            if any(w.lower() in joins for w in WORD.findall(p))]


def respace(chapters: list[Chapter], client, on_progress=None) -> tuple[list[Chapter], RespaceRun]:
    """Put the spaces back where a scan lost them, in the paragraphs that need it.

    Untouched everywhere the check refuses a reply or the call fails, so the
    worst outcome of a bad model or a dropped connection is the book exactly as
    the file had it.
    """
    paragraphs = [p for chapter in chapters for p in chapter.paragraphs]
    run = RespaceRun()
    wanted = suspect(paragraphs)
    if not wanted:
        return chapters, run

    fixed: dict[int, str] = {}
    for done, index in enumerate(wanted):
        original = paragraphs[index]
        run.looked_at += 1
        try:
            reply = client.complete(
                SPACING_SYSTEM, SPACING_PROMPT.format(passage=original), MAX_TOKENS)
        except Exception:
            run.failed += 1
        else:
            taken = respaced(original, reply.text)
            if taken is None:
                run.refused += 1
            else:
                fixed[index] = taken
                run.repaired += 1
                run.words.extend(came_apart(original, taken)[:3])
        if on_progress:
            on_progress("respace", done + 1, len(wanted))

    if not fixed:
        return chapters, run
    out, at = [], 0
    for chapter in chapters:
        body = []
        for paragraph in chapter.paragraphs:
            body.append(fixed.get(at, paragraph))
            at += 1
        out.append(Chapter(chapter.number, chapter.title, body, chapter.part))
    return out, run


def came_apart(before: str, after: str) -> list[str]:
    """The words that are in the passage no longer, which are the ones repaired."""
    now = set(WORD.findall(after))
    return [w for w in WORD.findall(before) if w not in now]
