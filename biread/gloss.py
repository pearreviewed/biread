"""Per-paragraph glossing of the French, for hover in the reader.

The model is asked to divide a paragraph into hover units and explain each one
in context. What comes back is treated as a *proposal*: every unit is located in
the real paragraph by searching forward from the last one, and only its offsets
are kept. The reader then renders slices of the original text.

That is the whole safety argument. A model that drops a word, fixes an accent or
rewrites a contraction cannot put its version in front of a reader, because its
strings are never displayed — at worst the search fails and the paragraph goes
unglossed. Trusting the returned strings would make a silent corruption of the
book the cost of one bad response.

Nothing here prints; the caller reports.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Callable

from .cache import Cache
from .cleanup import Chapter
from .config import Config
from .errors import GlossError
from .language import FRENCH as LANGUAGE
from .llm import LLMClient
from .translate import Unit, batch, hash_text, parse_response

# Output is several times the input here, so batches are smaller than translation's.
BATCH_CHARS = 2500
MAX_TOKENS = 8192
CHARS_PER_TOKEN = 4

#: Field separator. A broken bar does not occur in French prose, and unlike the
#: invisible separators it is obvious in a terminal when a response goes wrong.
FIELD = "¦"

SYSTEM_PROMPT = f"""You are annotating literary {LANGUAGE.name} prose for a bilingual \
reading edition. Divide each paragraph into hover units and explain each one in its context.

{LANGUAGE.gloss_rules}

FOR EACH UNIT, one line, fields separated by {FIELD}:
surface {FIELD} part of speech {FIELD} English gloss in this context

THE SURFACE FIELD IS COPIED, NOT WRITTEN. Reproduce it exactly as it appears in the \
paragraph — same spelling, same accents, same apostrophes, same case. Do not correct, \
modernise, expand or normalise anything. It is matched against the source character for \
character, and a unit that does not match is discarded.

OUTPUT FORMAT — follow exactly:
For each paragraph, a line containing only the marker @@@N@@@ (N the paragraph's number), \
then that paragraph's unit lines. Then the next marker. Output nothing else: no \
commentary, no numbering, no blank lines between units."""

RETRY_NOTE = (
    f"\n\nYour previous response could not be used. Copy each surface exactly as it "
    f"appears in the paragraph, one unit per line, fields separated by {FIELD}, under "
    f"an @@@N@@@ marker. Nothing else."
)


@dataclass(frozen=True)
class GlossUnit:
    """A hover target, as a span of the paragraph it was found in."""

    start: int
    end: int
    pos: str
    gloss: str
    infinitive: str = ""
    perfect: str = ""


@dataclass
class GlossRun:
    glosses: dict[str, list[GlossUnit]]
    total: int
    glossed: int = 0
    rescued: int = 0  # of `glossed`, how many needed a second pass on their own
    unglossed: list[str] = field(default_factory=list)
    cost: float | None = None
    stopped_at_cap: bool = False


def body_units(chapters: list[Chapter]) -> list[Unit]:
    """Only body paragraphs. Chapter headings and anything cleanup left behind
    are apparatus, and glossing apparatus is paying for what nobody hovers."""
    return [Unit(hash_text(p), p) for c in chapters for p in c.paragraphs]


#: Cutting a sentence into units is a judgement the rules make, so a gloss is
#: only reusable while those rules hold. Keying the cache on the paragraph alone
#: would serve segmentation from a superseded rule set forever, with no way to
#: tell — the entries look identical. Folding the rules in means editing them
#: invalidates exactly what they produced, and nothing else.
RULES_VERSION = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:8]


def cache_key(paragraph_hash: str) -> str:
    return f"{paragraph_hash}.{RULES_VERSION}"


def parse_units(block: str) -> list[dict]:
    """One response block into raw unit dicts, before they are located."""
    units = []
    for line in block.splitlines():
        parts = [p.strip() for p in line.split(FIELD)]
        if len(parts) < 3 or not parts[0]:
            continue
        unit = {"surface": parts[0], "pos": parts[1], "gloss": parts[2],
                "infinitive": "", "perfect": ""}
        for extra in parts[3:]:
            key, _, value = extra.partition("=")
            if key.strip() == "inf":
                unit["infinitive"] = value.strip()
            elif key.strip() == "pc":
                unit["perfect"] = value.strip()
        units.append(unit)
    return units


# Models normalise typography however firmly they are told not to: a curly
# apostrophe comes back straight, an em dash as a hyphen, guillemets as quotes.
# French prose is one long chain of elisions — l'étoile, j'ai, qu'il — so
# byte-exact matching rejected 34 of 36 paragraphs on the first real run.
#
# These are folded for *matching only*. Offsets still point into the original,
# so what reaches the reader is still the source text, character for character.
FOLD = {
    "\u2019": "'", "\u2018": "'",
    "\u201c": '"', "\u201d": '"',
    "\u00ab": '"', "\u00bb": '"',
    "\u2014": "-", "\u2013": "-",
    "\u00a0": " ", "\u202f": " ", "\u2009": " ",
    "\u2026": "...",
}


def fold(text: str) -> tuple[str, list[int]]:
    """Normalised text, and a map from each normalised index to the original."""
    out: list[str] = []
    index: list[int] = []
    for position, char in enumerate(text):
        for folded in FOLD.get(char, char):
            out.append(folded)
            index.append(position)
    return "".join(out), index


WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# A hover is meant to explain one phrase. The model reliably drifts wider than
# that — whole relative clauses arrived as single units on the first real run —
# and the prompt alone did not hold it.
#
# A noun phrase may carry an adjective, so two content words are allowed:
# "un jeune homme". Anything that predicates may not, because its second content
# word is a subject or an object rather than part of the phrase — "le procès |
# dura", not "le procès dura". The part of speech comes from the model and can
# be wrong, but a wrong label only costs one hover: the words under it read as
# ordinary prose.
MAX_CONTENT_WORDS = 2
PREDICATE_POS_RE = re.compile(r"verb|clause|sentence", re.IGNORECASE)


def content_words(surface: str) -> list[str]:
    """The words in a unit that are not closed-class, folded for comparison."""
    return [w for w in WORD_RE.findall(surface.lower())
            if w not in LANGUAGE.function_words]


def over_broad(surface: str, pos: str = "") -> bool:
    limit = 1 if PREDICATE_POS_RE.search(pos) else MAX_CONTENT_WORDS
    return len(content_words(surface)) > limit


def anchor(paragraph: str, proposed: list[dict]) -> list[GlossUnit] | None:
    """Locate each proposed unit in the paragraph, in order.

    Returns None if any unit cannot be found at or after the previous one —
    the model has lost its place or invented words, and the whole segmentation
    is untrustworthy. Gaps between units are fine: they render as plain text.

    A unit wider than a phrase is dropped rather than rejected: it is a bundling
    mistake, not a sign the model lost the text, so the words under it simply
    read as prose while the rest of the paragraph keeps its hovers.
    """
    haystack, index = fold(paragraph)
    located: list[GlossUnit] = []
    cursor = 0
    for unit in proposed:
        surface = fold(unit["surface"])[0].strip()
        if not surface:
            continue
        found = haystack.find(surface, cursor)
        if found == -1:
            return None
        cursor = found + len(surface)
        if over_broad(unit["surface"], unit["pos"]):
            continue
        located.append(GlossUnit(
            start=index[found],
            end=index[found + len(surface) - 1] + 1,
            pos=unit["pos"],
            gloss=unit["gloss"],
            infinitive=unit["infinitive"],
            perfect=unit["perfect"],
        ))
    return located or None


def coverage(paragraph: str, units: list[GlossUnit]) -> float:
    """Share of the paragraph's non-space characters that are hoverable."""
    total = sum(1 for ch in paragraph if not ch.isspace())
    if not total:
        return 1.0
    covered = sum(
        1 for u in units for ch in paragraph[u.start:u.end] if not ch.isspace()
    )
    return covered / total


def encode(units: list[GlossUnit]) -> str:
    return json.dumps([asdict(u) for u in units], ensure_ascii=False)


def decode(payload: str) -> list[GlossUnit]:
    return [GlossUnit(**u) for u in json.loads(payload)]


def build_prompt(units: list[Unit], indices: list[int]) -> str:
    numbered = "\n\n".join(
        f"=== PARAGRAPH {n} ===\n{units[i].text}" for n, i in enumerate(indices)
    )
    return "Divide each paragraph below into hover units:\n\n" + numbered


def estimate(chapters: list[Chapter], cache: Cache, cfg: Config):
    from .translate import Estimate

    units = body_units(chapters)
    pending = [i for i, u in enumerate(units) if cache_key(u.hash) not in cache]
    batches = list(batch(units, pending, max_chars=BATCH_CHARS))
    body_chars = sum(len(units[i].text) for i in pending)

    input_tokens = (len(SYSTEM_PROMPT) * len(batches) + body_chars) // CHARS_PER_TOKEN
    # Every unit costs its surface again plus a gloss, a part of speech and
    # sometimes two verb forms. Calibrated against a real Micromégas run rather
    # than guessed: the first estimate used 3.5 and came in at a third of the
    # actual bill.
    output_tokens = int(body_chars * 5.3) // CHARS_PER_TOKEN
    return Estimate(
        total=len(units),
        cached=len(units) - len(pending),
        pending=len(pending),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cfg.estimate_cost(input_tokens, output_tokens),
    )


SENTENCE_END_RE = re.compile(r"(?<=[.!?…»])\s+")
RESCUE_CHARS = 700


def chunks(text: str, limit: int = RESCUE_CHARS) -> list[tuple[int, str]]:
    """Sentence-aligned pieces of a paragraph, as (offset, text).

    Each piece is a literal slice, so a unit anchored inside one lands in the
    paragraph by adding the offset and nothing else.
    """
    edges = [0, *(m.end() for m in SENTENCE_END_RE.finditer(text)), len(text)]
    spans = [(a, b) for a, b in zip(edges, edges[1:]) if text[a:b].strip()]

    out: list[tuple[int, str]] = []
    start = end = None
    for a, b in spans:
        if start is None or b - start > limit:
            if start is not None:
                out.append((start, text[start:end]))
            start = a
        end = b
    if start is not None:
        out.append((start, text[start:end]))
    return out


def _gloss_alone(client: LLMClient, text: str) -> list[GlossUnit] | None:
    """One passage, on its own. None if it will not anchor."""
    prompt = build_prompt([Unit("", text)], [0])
    try:
        completion = client.complete(SYSTEM_PROMPT, prompt, MAX_TOKENS)
    except Exception:
        return None
    if completion.truncated:
        return None
    try:
        blocks = parse_response(completion.text)
    except ValueError:
        return None
    return anchor(text, parse_units(blocks.get(0, "")))


def rescue(client: LLMClient, text: str) -> list[GlossUnit] | None:
    """A paragraph the batch could not anchor, tried again with less to track.

    Alone first — most failures are the model losing its place across a batch,
    and one paragraph by itself is usually enough. Failing that, sentence by
    sentence: a piece that will not anchor is dropped whole and reads as plain
    text, so drift stays inside the sentence that caused it instead of costing
    the paragraph its other eighty units.
    """
    located = _gloss_alone(client, text)
    if located:
        return located

    pieces = chunks(text)
    if len(pieces) < 2:
        return None

    out: list[GlossUnit] = []
    for offset, piece in pieces:
        found = _gloss_alone(client, piece)
        if found:
            out.extend(replace(u, start=u.start + offset, end=u.end + offset) for u in found)
    return out or None


def _gloss_batch(
    client: LLMClient, units: list[Unit], indices: list[int]
) -> dict[int, list[GlossUnit]]:
    """One batch, retried once when a segmentation cannot be anchored."""
    prompt = build_prompt(units, indices)
    for attempt in range(2):
        system = SYSTEM_PROMPT + (RETRY_NOTE if attempt else "")
        try:
            completion = client.complete(system, prompt, MAX_TOKENS)
        except Exception as e:
            raise GlossError(f"gloss request failed: {e}") from e
        if completion.truncated:
            raise GlossError(
                f"the model hit its {MAX_TOKENS}-token limit mid-paragraph. "
                f"Lower BATCH_CHARS in gloss.py and re-run."
            )
        try:
            blocks = parse_response(completion.text)
        except ValueError:
            continue

        anchored: dict[int, list[GlossUnit]] = {}
        for n, index in enumerate(indices):
            located = anchor(units[index].text, parse_units(blocks.get(n, "")))
            if located:
                anchored[n] = located
        if anchored:
            return anchored
    return {}


def gloss_book(
    chapters: list[Chapter],
    client: LLMClient,
    cache: Cache,
    cfg: Config,
    on_progress: Callable[[int, int], None] | None = None,
) -> GlossRun:
    """Gloss every uncached body paragraph.

    A paragraph whose segmentation will not anchor is left out rather than shown
    with text the model altered. It reads as ordinary prose with no hover
    targets, and is named in the run so it can be looked at.
    """
    units = body_units(chapters)
    glosses = {u.hash: decode(cache.get(cache_key(u.hash)))
               for u in units if cache_key(u.hash) in cache}
    run = GlossRun(glosses=glosses, total=len(units))

    pending = [i for i, u in enumerate(units) if u.hash not in glosses]
    if not pending:
        return run

    def capped() -> bool:
        run.cost = cfg.estimate_cost(client.input_tokens, client.output_tokens)
        return run.cost is not None and run.cost >= cfg.max_cost_usd

    def keep(unit: Unit, located: list[GlossUnit]) -> None:
        glosses[unit.hash] = located
        cache.update({cache_key(unit.hash): encode(located)})
        run.glossed += 1
        if on_progress:
            on_progress(len(glosses), run.total)

    failed: list[Unit] = []
    for group in batch(units, pending, max_chars=BATCH_CHARS):
        anchored = _gloss_batch(client, units, group)
        for n, index in enumerate(group):
            located = anchored.get(n)
            if located:
                keep(units[index], located)
            else:
                failed.append(units[index])

        if capped():
            run.stopped_at_cap = True
            run.unglossed = [u.text[:60] for u in failed]
            return run

    for unit in failed:
        located = rescue(client, unit.text) if not run.stopped_at_cap else None
        if located:
            keep(unit, located)
            run.rescued += 1
        else:
            run.unglossed.append(unit.text[:60])
        run.stopped_at_cap = run.stopped_at_cap or capped()

    return run
