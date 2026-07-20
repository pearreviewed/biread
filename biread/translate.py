"""Paragraph translation, cached per paragraph.

The English produced here is the PRIMARY reading text — it must be genuinely
good prose, not a literal crib.

Nothing in this module prints. Callers pass `on_progress` for a live counter
and read the returned `TranslationRun` for everything else.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Callable, Iterator

from .cache import Cache
from .cleanup import Chapter
from .config import Config
from .errors import TranslationError
from .llm import LLMClient

BATCH_SIZE = 4  # within the spec'd 3-5 paragraphs per call
BATCH_MAX_CHARS = 6000  # keeps a batch of long paragraphs inside MAX_TOKENS
MAX_TOKENS = 8192
CHARS_PER_TOKEN = 4  # rough heuristic, estimates only — no tokenizer call

SYSTEM_PROMPT = """You are translating literary French prose into English for a bilingual \
reading edition. The English translation is the PRIMARY reading text — it must read as \
genuinely good, idiomatic English prose, not a literal crib.

Rules:
- Preserve the register, rhythm, and tone of the French. Restructure sentences freely where \
English calls for a different shape — do not mirror French syntax mechanically.
- Do not drop or add content. Every clause in the French, including subordinate clauses, \
must appear in the English — never merge or omit a clause for concision.
- Keep paragraph boundaries exactly as given: one input paragraph produces exactly one \
output paragraph. Never split or merge paragraphs.
- For older/period texts (18th-19th century and earlier), preserve irony, deadpan, and \
understatement rather than explaining or clarifying the joke. Keep period formality rather \
than modernizing toward casual contemporary English.
- Use the given context (the preceding paragraph, in French and, if available, its already- \
established English translation) to keep tense, register, and the tu/vous relationship \
consistent with what came before — but do not translate the context itself, only the \
numbered paragraphs.

OUTPUT FORMAT — follow exactly:
For each paragraph, output a line containing only the marker @@@N@@@ (with N the paragraph's \
number), then the English translation on the following line(s). Then the next marker, and so \
on. The translation text may freely contain quotation marks, guillemets, dashes, and any \
punctuation — you do NOT need to escape anything, because this is plain text, not JSON. Output \
nothing else: no commentary, no JSON, no code fences, no blank marker lines."""

RETRY_NOTE = (
    "\n\nYour previous response could not be parsed. Output ONLY the @@@N@@@ markers and "
    "translations, one marker per line, nothing else."
)

# Chosen so it cannot plausibly occur inside a translation, keeping the parse
# immune to the quotes, guillemets, and newlines that break JSON.
MARKER_RE = re.compile(r"^@@@(\d+)@@@[ \t]*$", re.MULTILINE)


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Unit:
    """One translatable string: a body paragraph or a chapter title."""

    hash: str
    text: str


@dataclass(frozen=True)
class Estimate:
    total: int
    cached: int
    pending: int
    input_tokens: int
    output_tokens: int
    cost: float | None


@dataclass
class TranslationRun:
    translations: dict[str, str]
    total: int
    translated: int = 0
    cost: float | None = None
    stopped_at_cap: bool = False
    batches: list[list[int]] = field(default_factory=list)


def flatten(chapters: list[Chapter]) -> list[Unit]:
    """Every translatable unit in the book, in reading order.

    Chapter titles are included alongside body paragraphs so both get cached
    and both benefit from surrounding context. The renderer looks titles back
    up by hash; they are not part of the paragraph-pairing sequence.
    """
    units: list[Unit] = []
    for chapter in chapters:
        if chapter.title:
            units.append(Unit(hash_text(chapter.title), chapter.title))
        units.extend(Unit(hash_text(p), p) for p in chapter.paragraphs)
    return units


def pending_indices(units: list[Unit], done: dict[str, str] | Cache) -> list[int]:
    """Indices of units still needing translation, one per distinct text.

    Books repeat strings — section breaks, refrains, duplicated titles. Sending
    each occurrence separately would pay for the same translation twice.
    """
    seen: set[str] = set()
    out = []
    for i, unit in enumerate(units):
        if unit.hash in done or unit.hash in seen:
            continue
        seen.add(unit.hash)
        out.append(i)
    return out


def batch(
    units: list[Unit],
    indices: list[int],
    count: int = BATCH_SIZE,
    max_chars: int = BATCH_MAX_CHARS,
) -> Iterator[list[int]]:
    """Group pending indices into API calls, bounded by count and total size.

    Glossing reuses this with a tighter char budget: its output runs several
    times the length of its input, where a translation runs about even.
    """
    current: list[int] = []
    chars = 0
    for idx in indices:
        size = len(units[idx].text)
        if current and (len(current) >= count or chars + size > max_chars):
            yield current
            current, chars = [], 0
        current.append(idx)
        chars += size
    if current:
        yield current


def parse_response(raw: str) -> dict[int, str]:
    """Parse a @@@N@@@-delimited response into {index: translation}.

    Content-agnostic: everything between one marker and the next belongs to
    that marker, so quotes, guillemets, and newlines in the prose cannot break
    it the way they broke JSON string values.
    """
    matches = list(MARKER_RE.finditer(raw))
    if not matches:
        raise ValueError("no @@@N@@@ markers found in model response")
    out: dict[int, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        out[int(m.group(1))] = raw[m.end() : end].strip()
    return out


def build_prompt(units: list[Unit], translations: dict[str, str], indices: list[int]) -> str:
    context = ""
    prev = indices[0] - 1
    if prev >= 0:
        established = translations.get(units[prev].hash)
        context = (
            "CONTEXT — preceding paragraph, for continuity only (do not translate this):\n"
            f"French: {units[prev].text}\n"
            + (f"English (established): {established}\n\n" if established else "English: (not yet translated)\n\n")
        )
    numbered = "\n\n".join(
        f"=== PARAGRAPH {n} ===\n{units[idx].text}" for n, idx in enumerate(indices)
    )
    return (
        context
        + "Translate each of the following French paragraphs into English, using the "
        + "@@@N@@@ output format described above:\n\n"
        + numbered
    )


def estimate(chapters: list[Chapter], cache: Cache, cfg: Config) -> Estimate:
    """What a run would cost, without calling the API."""
    units = flatten(chapters)
    indices = pending_indices(units, cache)
    batches = list(batch(units, indices))

    body_chars = sum(len(units[i].text) for i in indices)
    # The system prompt goes out once per batch, and each batch resends its
    # first paragraph's predecessor as continuity context.
    context_chars = sum(len(units[max(b[0] - 1, 0)].text) for b in batches)
    input_chars = len(SYSTEM_PROMPT) * len(batches) + body_chars + context_chars

    input_tokens = input_chars // CHARS_PER_TOKEN
    output_tokens = math.ceil(body_chars * 1.15) // CHARS_PER_TOKEN
    return Estimate(
        total=len(units),
        cached=len(units) - len(indices),
        pending=len(indices),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost=cfg.estimate_cost(input_tokens, output_tokens),
    )


def _translate_batch(
    client: LLMClient, units: list[Unit], translations: dict[str, str], indices: list[int]
) -> dict[int, str]:
    """One batch, with a single retry when the model ignores the output format."""
    prompt = build_prompt(units, translations, indices)
    last_error = ""
    for attempt in range(2):
        system = SYSTEM_PROMPT + (RETRY_NOTE if attempt else "")
        try:
            completion = client.complete(system, prompt, MAX_TOKENS)
        except Exception as e:  # provider SDKs raise their own hierarchies
            raise TranslationError(f"translation request failed: {e}") from e

        if completion.truncated:
            raise TranslationError(
                f"the model hit its {MAX_TOKENS}-token output limit mid-translation "
                f"(paragraph {indices[0]} onward). The source paragraph is likely "
                f"unusually long; split it in the source text and re-run."
            )
        try:
            parsed = parse_response(completion.text)
        except ValueError as e:
            last_error = str(e)
            continue
        missing = [n for n in range(len(indices)) if n not in parsed]
        if missing:
            last_error = f"response was missing paragraph(s) {missing}"
            continue
        return parsed

    raise TranslationError(f"could not parse the model's response after 2 attempts: {last_error}")


def translate_book(
    chapters: list[Chapter],
    client: LLMClient,
    cache: Cache,
    cfg: Config,
    on_progress: Callable[[int, int], None] | None = None,
) -> TranslationRun:
    """Translate every uncached paragraph. Returns hash -> English for the whole
    book, previously-cached entries included.

    Stops early — without losing completed work, since each batch is cached as
    soon as it returns — if the running cost estimate reaches cfg.max_cost_usd.
    Re-run to pick up where it left off.
    """
    units = flatten(chapters)
    translations = {u.hash: cache.get(u.hash) for u in units if u.hash in cache}
    run = TranslationRun(translations=translations, total=len(units))

    indices = pending_indices(units, translations)
    if not indices:
        return run

    for group in batch(units, indices):
        parsed = _translate_batch(client, units, translations, group)
        fresh = {units[idx].hash: parsed[n] for n, idx in enumerate(group)}
        translations.update(fresh)
        cache.update(fresh)

        run.translated += len(fresh)
        run.batches.append(group)
        if on_progress:
            on_progress(len(translations), run.total)

        run.cost = cfg.estimate_cost(client.input_tokens, client.output_tokens)
        if run.cost is not None and run.cost >= cfg.max_cost_usd:
            run.stopped_at_cap = True
            return run

    run.cost = cfg.estimate_cost(client.input_tokens, client.output_tokens)
    return run
