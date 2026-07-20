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

import json
from dataclasses import asdict, dataclass, field
from typing import Callable

from .cache import Cache
from .cleanup import Chapter
from .config import Config
from .errors import GlossError
from .llm import LLMClient
from .translate import Unit, batch, hash_text, parse_response

# Output is several times the input here, so batches are smaller than translation's.
BATCH_CHARS = 2500
MAX_TOKENS = 8192
CHARS_PER_TOKEN = 4

#: Field separator. A broken bar does not occur in French prose, and unlike the
#: invisible separators it is obvious in a terminal when a response goes wrong.
FIELD = "¦"

SYSTEM_PROMPT = f"""You are annotating literary French prose for a bilingual reading \
edition. Divide each paragraph into hover units and explain each one in its context.

WHAT A UNIT IS:
- A unit is a content word together with the function words attached to it. Articles, \
prepositions, pronouns, and auxiliaries are never units of their own — they belong with \
the word they govern. "Sur la table" is ONE unit, not three. "il se leva" is ONE unit.
- Punctuation between units is not part of any unit.
- Cover the paragraph in order, from beginning to end.

FOR EACH UNIT, one line, fields separated by {FIELD}:
surface {FIELD} part of speech {FIELD} English gloss in this context

Then, only where they apply, append further fields:
- inf=<infinitive> — ONLY for verbs, and only when the unit is not already an infinitive.
- pc=<passé composé> — ONLY for verbs in the passé simple, rewritten into the passé \
composé with the correct auxiliary and agreement (il monta -> il est monté; \
elle s'assit -> elle s'est assise).

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
    unglossed: list[str] = field(default_factory=list)
    cost: float | None = None
    stopped_at_cap: bool = False


def body_units(chapters: list[Chapter]) -> list[Unit]:
    """Only body paragraphs. Chapter headings and anything cleanup left behind
    are apparatus, and glossing apparatus is paying for what nobody hovers."""
    return [Unit(hash_text(p), p) for c in chapters for p in c.paragraphs]


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


def anchor(paragraph: str, proposed: list[dict]) -> list[GlossUnit] | None:
    """Locate each proposed unit in the paragraph, in order.

    Returns None if any unit cannot be found at or after the previous one —
    the model has altered the text or lost its place, and the whole segmentation
    is untrustworthy. Gaps between units are fine: they render as plain text.
    """
    located: list[GlossUnit] = []
    cursor = 0
    for unit in proposed:
        surface = unit["surface"]
        found = paragraph.find(surface, cursor)
        if found == -1:
            return None
        located.append(GlossUnit(
            start=found,
            end=found + len(surface),
            pos=unit["pos"],
            gloss=unit["gloss"],
            infinitive=unit["infinitive"],
            perfect=unit["perfect"],
        ))
        cursor = found + len(surface)
    return located


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
    pending = [i for i, u in enumerate(units) if u.hash not in cache]
    batches = list(batch(units, pending, max_chars=BATCH_CHARS))
    body_chars = sum(len(units[i].text) for i in pending)

    input_tokens = (len(SYSTEM_PROMPT) * len(batches) + body_chars) // CHARS_PER_TOKEN
    # Every unit costs its surface again plus a gloss, a part of speech and
    # sometimes two verb forms — several times the paragraph it came from.
    output_tokens = int(body_chars * 3.5) // CHARS_PER_TOKEN
    return Estimate(
        total=len(units),
        cached=len(units) - len(pending),
        pending=len(pending),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cfg.estimate_cost(input_tokens, output_tokens),
    )


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
    glosses = {u.hash: decode(cache.get(u.hash)) for u in units if u.hash in cache}
    run = GlossRun(glosses=glosses, total=len(units))

    pending = [i for i, u in enumerate(units) if u.hash not in glosses]
    if not pending:
        return run

    for group in batch(units, pending, max_chars=BATCH_CHARS):
        anchored = _gloss_batch(client, units, group)
        fresh = {}
        for n, index in enumerate(group):
            unit = units[index]
            located = anchored.get(n)
            if not located:
                run.unglossed.append(unit.text[:60])
                continue
            glosses[unit.hash] = located
            fresh[unit.hash] = encode(located)

        cache.update(fresh)
        run.glossed += len(fresh)
        if on_progress:
            on_progress(len(glosses), run.total)

        run.cost = cfg.estimate_cost(client.input_tokens, client.output_tokens)
        if run.cost is not None and run.cost >= cfg.max_cost_usd:
            run.stopped_at_cap = True
            return run

    run.cost = cfg.estimate_cost(client.input_tokens, client.output_tokens)
    return run
