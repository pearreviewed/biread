"""One page of the book, done for real, before the whole book is paid for.

A reader deciding whether to spend is otherwise asked to trust an estimate and a
model name. A sample is the same pipeline over three paragraphs: what comes back
is what the book will read like, for the price of a single call — and it can be
asked for again on the next page, and the next, until the reader is convinced.

Nothing here is cached: a sample is bought to be looked at now, and the book's
own cache should not fill with stray paragraphs from a preview.
"""
from __future__ import annotations

from dataclasses import dataclass

from .align import Embed, embed_match, prose_only, trim_matter
from .build import check_usable
from .cache import Cache
from .cleanup import Chapter
from .config import Config
from .llm import LLMClient
from .translate import hash_text, translate_book

PAGE_PARAGRAPHS = 3  # a page's worth of prose


@dataclass
class SamplePage:
    index: int
    total: int
    source: list[str]
    target: list[str]  # one per source paragraph, "" where nothing matched
    cost: float | None


def pages(chapters: list[Chapter]) -> list[list[str]]:
    """Body paragraphs sliced into pages of PAGE_PARAGRAPHS."""
    body = [p for chapter in chapters for p in chapter.paragraphs]
    return [body[at : at + PAGE_PARAGRAPHS] for at in range(0, len(body), PAGE_PARAGRAPHS)]


def sample_translate(
    chapters: list[Chapter],
    client: LLMClient,
    cfg: Config,
    target: str,
    index: int = 0,
) -> SamplePage:
    """Translate one page, on the model and the key the whole book would use."""
    index, total, source = _page(chapters, "The book", index)
    # Billed as the difference, not the client's running total: a reader clicking
    # through samples on one client would otherwise see the third page priced at
    # three pages.
    before_in, before_out = client.input_tokens, client.output_tokens
    run = translate_book([Chapter(None, None, source)], client, Cache(None), cfg, target=target)
    return SamplePage(
        index=index,
        total=total,
        source=source,
        target=[run.translations.get(hash_text(p), "") for p in source],
        cost=cfg.estimate_cost(client.input_tokens - before_in, client.output_tokens - before_out),
    )


def sample_align(
    chapters: list[Chapter],
    published_chapters: list[Chapter],
    embed: Embed,
    index: int = 0,
    window: int = 40,
) -> SamplePage:
    """Set one page of the original beside the published edition brought for it.

    Aligning the page as the finished book would means embedding both editions
    entire — minutes of work, and the reader is waiting on three paragraphs. So
    the published edition is searched only where the page can plausibly be, and
    matched there by the same machinery the full alignment uses.

    Cost is left None: the caller owns the embedding model and prices it.
    """
    index, total, source = _page(chapters, "The book", index)
    published = prose_only(
        [p for c in _body(published_chapters, "The published translation") for p in c.paragraphs]
    )
    return SamplePage(
        index=index,
        total=total,
        source=source,
        target=embed_match(source, _window(published, index, total, window), embed),
        cost=None,
    )


def _body(chapters: list[Chapter], label: str) -> list[Chapter]:
    """The book as `build_reader` takes it: refused if it never broke into
    paragraphs, and trimmed to its body, so a sample opens on prose and not on a
    title page."""
    check_usable(chapters, label)
    return [c for c in trim_matter(chapters) if c.paragraphs] or chapters


def _page(chapters: list[Chapter], label: str, index: int) -> tuple[int, int, list[str]]:
    """The page asked for, its index wrapped so "another page" can count forever."""
    every = pages(_body(chapters, label))
    index %= len(every)
    return index, len(every), every[index]


def _window(published: list[str], index: int, total: int, window: int) -> list[str]:
    """The stretch of the published edition the page's counterpart lies in.

    Two editions of a book run in the same order, so a page a third of the way
    through one is about a third of the way through the other; `window`
    paragraphs either side absorbs how differently they divide their text.
    """
    at = round(index / total * len(published))
    return published[max(at - window, 0) : at + PAGE_PARAGRAPHS + window]
