"""Score an alignment without anyone having to label one.

Every matcher in this repository has been judged by coverage and by eye, and the
record of that is three of them built, measured and reverted. Coverage cannot do
the job: it says how much of the French found *something*, never whether the
something was right, so a matcher that confidently pairs the wrong paragraphs
scores better than one that honestly leaves them blank.

What settles it is two files carrying the *same translation*. Align the French
against each of them and every French paragraph should come back holding the same
English twice. Where the two answers differ, one of them is wrong — and that is a
number, measured off real editions, with no human labels in it and no judgement
from us. Nausea is the pair that makes it possible: Lloyd Alexander's 1949
translation exists here both as a digitally typeset PDF and as an Internet Archive
scan, so the two files disagree about paragraph breaks, spelling and apparatus
while agreeing about every word of the book.

It is a measuring instrument and not a test: it needs real editions and a real
embedding model, so it lives here and is run by hand rather than in CI. A fake
embedder would prove the wiring and nothing about the matching, which is the
lesson this file exists to stop paying for again.

    python -m biread.score FRENCH ENGLISH_A ENGLISH_B [--local] [--cache DIR]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .align import Embed, align_published, open_together
from .build import recut
from .cleanup import Chapter, clean
from .errors import BireadError
from .extract import get_extractor
from .llm.embed import BATCH
from .translate import hash_text

#: How much of the shorter reading must be found inside the longer before the two
#: are the same passage. Generous, because these are two copies of one English
#: translation: what stands between them is OCR misreading a word here and there,
#: and one file carrying more of the passage than the other where their paragraph
#: breaks disagree. A different passage shares only its commonest words.
SAME_PASSAGE = 0.6

#: Enough of a passage to recognise it by. Comparison is quadratic in the length
#: of what it is shown, and a French paragraph can be handed a page of English
#: where a translator split it; the opening of each is plenty to tell two
#: passages apart.
COMPARE_WORDS = 120

_NOISE = re.compile(r"[^0-9a-z]+")


def _plain(text: str) -> list[str]:
    """A reading reduced to what neither OCR nor typography can change about it:
    its words, lowercased, stripped of punctuation and quotation marks."""
    return _NOISE.sub(" ", text.lower()).split()[:COMPARE_WORDS]


def same_passage(left: str, right: str) -> float:
    """How much of the shorter reading is found, in order, inside the longer.

    Deliberately not `align.similarity`, and that mistake is worth keeping written
    down: it drops stopwords and words under three letters and then demands two
    content words in common, which is right for deciding whether a French
    paragraph and an English one are the same passage, and nonsense here. `"It's
    hot."` reduces to a single content word, so under that measure a short line of
    dialogue could never agree with an identical copy of itself, and the first run
    of this instrument reported eighty-one disagreements of which most were a line
    of speech against its own reflection.

    Compared word by word and not character by character, which was the second
    attempt and worse: over characters, `The dog runs.` and `The mountain is far
    off.` share two thirds of the shorter one in scattered letters and pass for
    the same sentence. Words are what a passage is made of, and a wrong passage
    shares only the commonest of them.

    What this cannot see is a one-word paragraph whose one word OCR mangled —
    `Touche!` arriving as `44 ” Touch*!`. It reads as a disagreement, which is the
    safe direction for an instrument to be wrong in: it under-reports agreement
    and so never flatters the matcher it is grading.
    """
    a, b = _plain(left), _plain(right)
    if not a or not b:
        return 0.0
    blocks = SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    return sum(block.size for block in blocks) / min(len(a), len(b))


@dataclass
class Score:
    """What two readings of one translation agreed and disagreed about."""

    total: int = 0            # French paragraphs
    agreed: int = 0           # both placed English, and it is the same passage
    disagreed: int = 0        # both placed English, and it is not
    only_a: int = 0
    only_b: int = 0
    neither: int = 0
    examples: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def judged(self) -> int:
        """Paragraphs where both editions placed something, so the two answers
        can be held against each other. The rest are not evidence either way."""
        return self.agreed + self.disagreed

    @property
    def accuracy(self) -> float | None:
        """The headline: of the paragraphs both editions answered, how many
        answered the same. None where nothing was comparable."""
        return self.agreed / self.judged if self.judged else None

    @property
    def answered(self) -> float:
        """How much of the French either edition placed anything against. Kept
        beside accuracy on purpose: a matcher can buy agreement by declining to
        answer, and this is the number that catches it doing so."""
        return (self.total - self.neither) / self.total if self.total else 0.0


def load(path: Path) -> list[Chapter]:
    if not path.exists():
        raise BireadError(f"file not found: {path}")
    return clean(get_extractor(path).extract(path), from_pdf=path.suffix.lower() == ".pdf")[0]


def place(french: list[Chapter], published: list[Chapter], embed: Embed) -> dict[str, str]:
    """One edition set beside the French exactly as the align route does it.

    The same three steps in the same order as `build.build_aligned` — cut to where
    the two editions open together, cut a flat edition to the other's shape, then
    match — because a score taken off a shorter path would be scoring something
    the reader never gets.

    Refuses the one case that would score zero while looking like a bad matcher:
    a French edition with no paragraph breaks is re-cut to each counterpart's
    shape, so its paragraphs are different text in the two runs and nothing can
    be held against anything. The comparison is keyed on the French, and that
    only works while the French is the same book both times.
    """
    french, published, _, _ = open_together(french, published, embed)
    french, published, cut = recut(french, published)
    if cut == "original":
        raise BireadError(
            "the French edition arrived with no paragraph breaks, so it is re-cut "
            "to each counterpart and the two runs no longer share a paragraph to "
            "compare. Score with a French file that keeps its own paragraphing."
        )
    return align_published(french, published, embed=embed)[0]


def compare(french: list[Chapter], a: dict[str, str], b: dict[str, str], keep: int = 12) -> Score:
    """Hold two readings of one translation against each other, paragraph by
    paragraph."""
    score = Score()
    for paragraph in (p for chapter in french for p in chapter.paragraphs):
        key = hash_text(paragraph)
        left, right = a.get(key, ""), b.get(key, "")
        score.total += 1
        if left and right:
            if same_passage(left, right) >= SAME_PASSAGE:
                score.agreed += 1
            else:
                score.disagreed += 1
                if len(score.examples) < keep:
                    score.examples.append((paragraph, left, right))
        elif left:
            score.only_a += 1
        elif right:
            score.only_b += 1
        else:
            score.neither += 1
    return score


def report(score: Score, names: tuple[str, str]) -> None:
    accuracy = "n/a" if score.accuracy is None else f"{score.accuracy:.1%}"
    print(f"\n{score.total:,} French paragraphs, {score.answered:.1%} answered by at least one edition")
    print(f"  agreed     {score.agreed:6,}   the same passage from both files")
    print(f"  disagreed  {score.disagreed:6,}   two different passages — at least one is wrong")
    print(f"  only {names[0][:18]:18} {score.only_a:6,}")
    print(f"  only {names[1][:18]:18} {score.only_b:6,}")
    print(f"  neither    {score.neither:6,}")
    print(f"\nAgreement on what both answered: {accuracy}")
    if score.examples:
        print("\nWhere they disagree:")
        for original, left, right in score.examples:
            print(f"  FR {original[:74]}")
            print(f"   A {left[:74]}")
            print(f"   B {right[:74]}\n")


#: How many times a batch is asked for again before the run is given up on.
#: Scoring a book is twenty minutes of embedding, and the first attempt at it
#: died on a read timeout at the far end with nineteen of those minutes already
#: paid for. A transient failure must not cost the run.
ATTEMPTS = 4


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:24]


class _Cached:
    """An embedder that remembers, so re-running the comparison costs nothing.

    Vectors are kept at four decimals: cosine is unmoved at that precision and the
    file is a third the size, which matters when a book is four thousand
    paragraphs of three thousand dimensions.

    Written to disk after every batch rather than at the end of every call, and
    retried on failure, because both of those were learnt the same way: the run
    that was to produce the first score reached the second edition and lost the
    lot to one timed-out request.
    """

    def __init__(self, embed: Embed, path: Path | None, sleep=time.sleep):
        self._embed = embed
        self._path = path
        self._sleep = sleep
        self._seen: dict[str, list[float]] = {}
        if path and path.exists():
            with gzip.open(path, "rt") as handle:
                self._seen = json.load(handle)

    def __call__(self, texts: list[str]) -> list[list[float]]:
        keys = [_key(t) for t in texts]
        # Deduplicated: a book repeats a short line of dialogue, and paying to
        # embed the same string twice in one call is simply paying twice.
        fresh = list(dict.fromkeys(t for t, k in zip(texts, keys) if k not in self._seen))
        if fresh:
            print(f"  embedding {len(fresh):,} of {len(texts):,}…", flush=True)
            for start in range(0, len(fresh), BATCH):
                batch = fresh[start:start + BATCH]
                for text, vector in zip(batch, self._attempt(batch)):
                    self._seen[_key(text)] = [round(x, 4) for x in vector]
                self._save()
        return [self._seen[k] for k in keys]

    def _attempt(self, batch: list[str]) -> list[list[float]]:
        for attempt in range(1, ATTEMPTS + 1):
            try:
                return self._embed(batch)
            except (RuntimeError, OSError) as exc:
                if attempt == ATTEMPTS:
                    raise BireadError(
                        f"the embedding model stopped answering after {ATTEMPTS} "
                        f"attempts ({exc}). Everything embedded so far is cached, "
                        f"so re-running resumes rather than starting again."
                    ) from exc
                print(f"    attempt {attempt} failed ({exc}); retrying…", flush=True)
                self._sleep(2 ** attempt)
        raise AssertionError("unreachable")  # pragma: no cover

    def _save(self) -> None:
        if not self._path:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(self._path, "wt") as handle:
            json.dump(self._seen, handle)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m biread.score",
        description="Align one French edition against two files of the same "
                    "translation, and measure how far the two answers agree.",
    )
    parser.add_argument("french", type=Path)
    parser.add_argument("edition_a", type=Path)
    parser.add_argument("edition_b", type=Path)
    parser.add_argument("--local", action="store_true",
                        help="embed on a local Ollama instead of a cloud model — free")
    parser.add_argument("--embed-model", default=None)
    parser.add_argument("--cache", type=Path, default=Path("cache/score-vectors.json.gz"),
                        help="where to keep vectors so a re-run is free")
    return parser


def main(argv: list[str] | None = None) -> int:
    from .publish import embedder_for

    args = build_parser().parse_args(argv)
    try:
        embedder = embedder_for(args)
        embed = _Cached(embedder.embed, args.cache)
        french = load(args.french)
        print(f"French: {sum(len(c.paragraphs) for c in french):,} paragraphs")
        placed = []
        for path in (args.edition_a, args.edition_b):
            edition = load(path)
            print(f"{path.name}: {sum(len(c.paragraphs) for c in edition):,} paragraphs")
            placed.append(place(french, edition, embed))
        report(compare(french, *placed), (args.edition_a.name, args.edition_b.name))
        print(f"\nEmbedding tokens this run: {embedder.input_tokens:,}")
    except BireadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
