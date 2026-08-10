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

# The gloss's explanation language follows the target; `gloss_system_prompt("English")`
# is the byte-for-byte prompt this shipped with, so RULES_VERSION (below) is
# unchanged for English and existing gloss caches stay valid. The source stays
# French (LANGUAGE), and so do the segmentation rules.
def gloss_system_prompt(gloss_lang: str = "English") -> str:
    return f"""You are annotating literary {LANGUAGE.name} prose for a bilingual \
reading edition. Divide each paragraph into hover units and explain each one in its context.

{LANGUAGE.gloss_rules}

FOR EACH UNIT, one line, fields separated by {FIELD}:
surface {FIELD} part of speech {FIELD} {gloss_lang} gloss {FIELD} inf=…
The last appears only on verbs, per the rules above:
il disséqua {FIELD} verb {FIELD} dissected {FIELD} inf=disséquer
un jeune homme {FIELD} noun phrase {FIELD} a young man

THE SURFACE FIELD IS COPIED, NOT WRITTEN. Reproduce it exactly as it appears in the \
paragraph — same spelling, same accents, same apostrophes, same case. Do not correct, \
modernise, expand or normalise anything. It is matched against the source character for \
character, and a unit that does not match is discarded.

OUTPUT FORMAT — follow exactly:
For each paragraph, a line containing only the marker @@@N@@@ (N the paragraph's number), \
then that paragraph's unit lines. Then the next marker. Output nothing else: no \
commentary, no numbering, no blank lines between units."""


SYSTEM_PROMPT = gloss_system_prompt("English")

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


@dataclass
class GlossRun:
    #: Every gloss the book will carry, including any an earlier session left in
    #: the cache beyond what this run was asked for.
    glosses: dict[str, list[GlossUnit]]
    #: The job as asked for, which on a book glossed only at its opening is the
    #: opening and not the book. Counting the book here quoted the wait for
    #: fifteen hundred paragraphs while forty were being made.
    total: int
    #: Of `total`, how many were already made before this run started.
    held: int = 0
    glossed: int = 0
    rescued: int = 0  # of `glossed`, how many needed a second pass on their own
    unglossed: list[str] = field(default_factory=list)
    cost: float | None = None
    stopped_at_cap: bool = False

    @property
    def done(self) -> int:
        return self.held + self.glossed


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
        unit = {"surface": parts[0], "pos": parts[1], "gloss": parts[2], "infinitive": ""}
        for extra in parts[3:]:
            key, _, value = extra.partition("=")
            if key.strip() == "inf":
                unit["infinitive"] = value.strip()
        # An infinitive that only echoes the surface says nothing: the verb
        # already is one, and a line repeating the word under the pointer is the
        # duplication this tooltip was cut back to avoid.
        if _same_form(unit["infinitive"], unit["surface"]):
            unit["infinitive"] = ""
        units.append(unit)
    return units


def _same_form(a: str, b: str) -> bool:
    return bool(a) and re.sub(r"\W+", "", a).casefold() == re.sub(r"\W+", "", b).casefold()


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


def _split_between_content(surface: str, markers: frozenset[str]) -> bool:
    """True if a marker word sits between two content words.

    Both "Moscovie ou Chine" (coordinator) and "citoyens de la terre"
    (preposition) are two logical parts on either side of a joining word. A
    leading "et …" or "de …" is not: nothing content-bearing precedes it.
    """
    seen_content = pending = False
    for word in WORD_RE.findall(surface.lower()):
        if word in markers and seen_content:
            pending = True
        elif word not in LANGUAGE.function_words:
            if pending:
                return True
            seen_content = True
    return False


def spans_coordination(surface: str) -> bool:
    return _split_between_content(surface, LANGUAGE.coordinators)


def joins_two_nouns(surface: str) -> bool:
    return _split_between_content(surface, LANGUAGE.prepositions)


def over_broad(surface: str, pos: str = "") -> bool:
    """Too wide to be one hover: more than a single content word and its
    grammatical hangers-on. An adjective stays with its noun (it sits flush,
    with no preposition between), but a second noun does not."""
    if spans_coordination(surface) or joins_two_nouns(surface):
        return True
    limit = 1 if PREDICATE_POS_RE.search(pos) else MAX_CONTENT_WORDS
    return len(content_words(surface)) > limit


def anchor(paragraph: str, proposed: list[dict]) -> list[GlossUnit] | None:
    """Locate each proposed unit in the paragraph, in order.

    Returns None if any unit cannot be found at or after the previous one —
    the model has lost its place or invented words, and the whole segmentation
    is untrustworthy. Gaps between units are fine: they render as plain text.

    This only locates; it does not judge width. Whether a unit is too broad to
    hover is decided by `displayable` at render time, so the cache holds the
    model's full proposal and the width rule can be retuned without paying to
    gloss again.
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
        located.append(GlossUnit(
            start=index[found],
            end=index[found + len(surface) - 1] + 1,
            pos=unit["pos"],
            gloss=unit["gloss"],
            infinitive=unit["infinitive"],
        ))
    return located or None


def displayable(paragraph: str, units: list[GlossUnit]) -> list[GlossUnit]:
    """Units narrow enough to show. The width rule is applied here, at the edge
    where units become hovers, rather than baked into the cache — so tightening
    it drops the offenders on the next render, with nothing to pay again.

    The echoed infinitive is dropped here for the same reason. Parsing already
    refuses to store one, but caches written before it did still hold them, and
    a line repeating the word under the pointer should not survive to the page on
    the strength of being old."""
    shown = []
    for u in units:
        surface = paragraph[u.start:u.end]
        if over_broad(surface, u.pos):
            continue
        shown.append(replace(u, infinitive="") if _same_form(u.infinitive, surface) else u)
    return shown


def protocol(gloss_lang: str = "English") -> dict:
    """Everything a client outside Python needs to gloss a paragraph itself.

    The reader glosses on demand, on its reader's own key, and to do that it has
    to run this stage's judgement: what to ask, how to read the answer, how to
    find each unit in the real text, and which are too broad to hover. The
    algorithms are necessarily written twice — once here, once in the reader —
    but the *data* they read is written once, and travels in the book.

    So a word added to the closed class reaches the reader in the next build
    rather than in a second edit to a second language, and the two cannot
    disagree about French while agreeing about French in a comment.
    """
    return {
        "prompt": gloss_system_prompt(gloss_lang),
        "field": FIELD,
        "fold": FOLD,
        "maxContentWords": MAX_CONTENT_WORDS,
        "predicatePos": PREDICATE_POS_RE.pattern,
        "functionWords": sorted(LANGUAGE.function_words),
        "coordinators": sorted(LANGUAGE.coordinators),
        "prepositions": sorted(LANGUAGE.prepositions),
    }


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


def estimate(chapters: list[Chapter], cache: Cache, cfg: Config,
             gloss_lang: str = "English", limit: int | None = None):
    from .translate import Estimate

    units = body_units(chapters)
    wanted = len(units) if limit is None else min(limit, len(units))
    pending = [i for i, u in enumerate(units[:wanted]) if cache_key(u.hash) not in cache]
    batches = list(batch(units, pending, max_chars=BATCH_CHARS))
    body_chars = sum(len(units[i].text) for i in pending)

    input_tokens = (len(gloss_system_prompt(gloss_lang)) * len(batches) + body_chars) // CHARS_PER_TOKEN
    # Every unit costs its surface again plus a gloss, a part of speech and
    # sometimes two verb forms. Calibrated against a real Micromégas run rather
    # than guessed: the first estimate used 3.5 and came in at a third of the
    # actual bill.
    output_tokens = int(body_chars * 5.3) // CHARS_PER_TOKEN
    return Estimate(
        # The job as asked for: with the book's opening glossed and the rest left
        # to the reader, the total is what the build will actually do.
        total=wanted,
        cached=wanted - len(pending),
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


def _gloss_alone(client: LLMClient, text: str, gloss_lang: str = "English") -> list[GlossUnit] | None:
    """One passage, on its own. None if it will not anchor."""
    prompt = build_prompt([Unit("", text)], [0])
    try:
        completion = client.complete(gloss_system_prompt(gloss_lang), prompt, MAX_TOKENS)
    except Exception:
        return None
    if completion.truncated:
        return None
    try:
        blocks = parse_response(completion.text)
    except ValueError:
        return None
    return anchor(text, parse_units(blocks.get(0, "")))


def rescue(client: LLMClient, text: str, gloss_lang: str = "English") -> list[GlossUnit] | None:
    """A paragraph the batch could not anchor, tried again with less to track.

    Alone first — most failures are the model losing its place across a batch,
    and one paragraph by itself is usually enough. Failing that, sentence by
    sentence: a piece that will not anchor is dropped whole and reads as plain
    text, so drift stays inside the sentence that caused it instead of costing
    the paragraph its other eighty units.
    """
    located = _gloss_alone(client, text, gloss_lang)
    if located:
        return located

    pieces = chunks(text)
    if len(pieces) < 2:
        return None

    out: list[GlossUnit] = []
    for offset, piece in pieces:
        found = _gloss_alone(client, piece, gloss_lang)
        if found:
            out.extend(replace(u, start=u.start + offset, end=u.end + offset) for u in found)
    return out or None


@dataclass
class GlossPlan:
    """Every request a gloss run has to make, and somewhere to put the answers.

    Split out of `gloss_book` so a caller can make those requests its own way.
    The browser's client blocks the worker until each one is answered, which is
    right for one request and is why a book of 1,500 paragraphs took an
    afternoon: nothing overlapped. With the plan in hand the page runs several at
    once and hands each reply back here.

    The judgement stays in one place. What to send, how to read a reply, what may
    be kept and what must be written off are this module's, whoever is driving.
    """
    units: list[Unit]
    #: Indices into `units`, batched to `BATCH_CHARS`. The uncached ones only.
    groups: list[list[int]]
    run: GlossRun
    gloss_lang: str = "English"
    #: Paragraphs no batch could anchor, waiting for the rescue pass.
    failed: list[Unit] = field(default_factory=list)

    def system(self, attempt: int = 0) -> str:
        return gloss_system_prompt(self.gloss_lang) + (RETRY_NOTE if attempt else "")

    def prompt(self, n: int) -> str:
        return build_prompt(self.units, self.groups[n])


#: The opening a build glosses when the reader takes it over the whole book,
#: measured in characters of the original rather than in paragraphs. What a
#: reader is given is a stretch of *reading*, and a flat paragraph count does not
#: buy the same stretch twice: a book set in short dialogue lines and a book set
#: in long ones share nothing but the number. 40 paragraphs is the whole of
#: Micromégas and thirteen spreads of La Nausée's four hundred and ninety-seven.
OPENING_CHARS = 40_000
#: A book of very long paragraphs still gets a few, and a book of very short ones
#: does not run away with the build.
OPENING_MIN = 40
OPENING_MAX = 400


def opening(chapters: list[Chapter], chars: int = OPENING_CHARS) -> int:
    """How many paragraphs of `chapters` make the opening, for `plan_gloss`.

    A book shorter than the budget comes out whole, which is what makes this
    scale rather than merely cap: nothing is left for a reader to buy on a book
    that fits.
    """
    units = body_units(chapters)
    taken = run = 0
    for unit in units:
        if run >= chars:
            break
        run += len(unit.text)
        taken += 1
    return min(len(units), max(OPENING_MIN, min(taken, OPENING_MAX)))


def plan_gloss(
    chapters: list[Chapter], cache: Cache, gloss_lang: str = "English", limit: int | None = None
) -> GlossPlan:
    """What is already glossed, and what is left to ask for.

    `limit` glosses only the book's opening. Glossing costs about four times
    translating and runs after both pages are written, so a reader who wants the
    hover can have the first pages of it now and the rest as they read — the book
    carries the protocol and finishes itself on their own key.
    """
    units = body_units(chapters)
    glosses = {u.hash: decode(cache.get(cache_key(u.hash)))
               for u in units if cache_key(u.hash) in cache}
    wanted = len(units) if limit is None else min(limit, len(units))
    pending = [i for i, u in enumerate(units[:wanted]) if u.hash not in glosses]
    return GlossPlan(
        units=units,
        groups=list(batch(units, pending, max_chars=BATCH_CHARS)),
        run=GlossRun(glosses=glosses, total=wanted, held=wanted - len(pending)),
        gloss_lang=gloss_lang,
    )


def absorb(
    plan: GlossPlan,
    n: int,
    text: str,
    cache: Cache,
    on_progress: Callable[[int, int], None] | None = None,
) -> int:
    """One batch's reply, anchored and kept. Returns how many paragraphs it glossed.

    A reply that will not parse glosses nothing, which is not the same as a
    failure: the caller decides whether to ask again. Nothing is written off here.
    """
    try:
        blocks = parse_response(text)
    except ValueError:
        return 0
    kept = 0
    for i, index in enumerate(plan.groups[n]):
        unit = plan.units[index]
        if unit.hash in plan.run.glosses:
            continue
        located = anchor(unit.text, parse_units(blocks.get(i, "")))
        if located:
            _keep(plan, cache, unit, located, on_progress)
            kept += 1
    return kept


def written_off(plan: GlossPlan, n: int) -> None:
    """Stop asking for this batch: whatever is still unglossed in it goes to the
    rescue pass, which tries each paragraph with less to keep track of."""
    for index in plan.groups[n]:
        unit = plan.units[index]
        if unit.hash not in plan.run.glosses:
            plan.failed.append(unit)


def rescue_failures(
    plan: GlossPlan,
    client: LLMClient,
    cache: Cache,
    on_progress: Callable[[int, int], None] | None = None,
    capped: Callable[[], bool] | None = None,
) -> None:
    """Every paragraph a batch lost, retried alone and then sentence by sentence."""
    for unit in plan.failed:
        located = None if plan.run.stopped_at_cap else rescue(client, unit.text, plan.gloss_lang)
        if located:
            _keep(plan, cache, unit, located, on_progress)
            plan.run.rescued += 1
        else:
            plan.run.unglossed.append(unit.text[:60])
        if capped and capped():
            plan.run.stopped_at_cap = True
    plan.failed = []


def _keep(
    plan: GlossPlan,
    cache: Cache,
    unit: Unit,
    located: list[GlossUnit],
    on_progress: Callable[[int, int], None] | None,
) -> None:
    plan.run.glosses[unit.hash] = located
    cache.update({cache_key(unit.hash): encode(located)})
    plan.run.glossed += 1
    if on_progress:
        on_progress(plan.run.done, plan.run.total)


def gloss_book(
    chapters: list[Chapter],
    client: LLMClient,
    cache: Cache,
    cfg: Config,
    on_progress: Callable[[int, int], None] | None = None,
    gloss_lang: str = "English",
    limit: int | None = None,
) -> GlossRun:
    """Gloss every uncached body paragraph, one request after another.

    A paragraph whose segmentation will not anchor is left out rather than shown
    with text the model altered. It reads as ordinary prose with no hover
    targets, and is named in the run so it can be looked at.
    """
    plan = plan_gloss(chapters, cache, gloss_lang, limit)
    run = plan.run
    if not plan.groups:
        return run

    def capped() -> bool:
        run.cost = cfg.estimate_cost(client.input_tokens, client.output_tokens)
        return run.cost is not None and run.cost >= cfg.max_cost_usd

    for n in range(len(plan.groups)):
        for attempt in range(2):
            try:
                completion = client.complete(plan.system(attempt), plan.prompt(n), MAX_TOKENS)
            except Exception as e:
                raise GlossError(f"gloss request failed: {e}") from e
            if completion.truncated:
                raise GlossError(
                    f"the model hit its {MAX_TOKENS}-token limit mid-paragraph. "
                    f"Lower BATCH_CHARS in gloss.py and re-run."
                )
            if absorb(plan, n, completion.text, cache, on_progress):
                break
        written_off(plan, n)

        if capped():
            run.stopped_at_cap = True
            run.unglossed = [u.text[:60] for u in plan.failed]
            return run

    rescue_failures(plan, client, cache, on_progress, capped)
    return run
