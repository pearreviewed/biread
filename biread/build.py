"""The build engine shared by the CLI and the in-browser builder.

`build_reader` runs the pipeline — translate, optionally align a published
edition, optionally gloss — and returns the finished reader as an HTML string
plus a report of what happened. It prints nothing and writes no files: callers
render progress and decide what to do with the result. The CLI wraps it with
terminal output and file writing; the browser wraps it with a progress bar and a
download.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .align import AlignmentReport, Embed, align_published, trim_matter
from .cache import Cache
from .cleanup import Chapter
from .config import Config
from .errors import ExtractError
from .gloss import GlossRun, gloss_book
from .llm import LLMClient
from .render import render_html
from .targets import ENGLISH, Target
from .translate import BatchFn, TranslationRun, translate_book

#: (stage, done, total); stage is "translate" or "gloss".
ProgressFn = Callable[[str, int, int], None]


@dataclass
class BuildResult:
    html: str
    translation: TranslationRun
    alignment: AlignmentReport | None = None
    published_note: str = ""
    gloss: GlossRun | None = None


def build_reader(
    *,
    title: str,
    chapters: list[Chapter],
    client: LLMClient,
    cache: Cache,
    cfg: Config,
    target: Target = ENGLISH,
    published_chapters: list[Chapter] | None = None,
    gloss: bool = False,
    gloss_client: LLMClient | None = None,
    gloss_cache: Cache | None = None,
    gloss_cfg: Config | None = None,
    on_progress: ProgressFn | None = None,
    on_text: BatchFn | None = None,
) -> BuildResult:
    # Checked before a single call is paid for: a book that never broke into
    # paragraphs would otherwise be translated in vast blocks, at vast cost.
    check_usable(chapters, "The book")
    if published_chapters is not None:
        check_usable(published_chapters, "The published translation")

    # The book is its body from here: the title page, table of contents and
    # licence that bracket it are dropped, so nothing before chapter one is
    # translated or rendered. This is the same trim the aligner applies, kept in
    # step so what the reader sees is what was aligned.
    chapters = [c for c in trim_matter(chapters) if c.paragraphs] or chapters

    run = translate_book(
        chapters, client, cache, cfg, _stage(on_progress, "translate"), target.name, on_text
    )

    published = alignment = None
    note = ""
    if published_chapters is not None:
        published, alignment = align_published(chapters, published_chapters, run.translations)
        note = published_note(alignment)

    gloss_run = glosses = None
    if gloss:
        gloss_run = gloss_book(
            chapters,
            gloss_client or client,
            gloss_cache if gloss_cache is not None else Cache(None),
            gloss_cfg or cfg.for_glossing(),
            _stage(on_progress, "gloss"),
            target.name,
        )
        glosses = gloss_run.glosses

    html = render_html(title, chapters, run.translations, published, note, glosses, None, target)
    return BuildResult(
        html=html, translation=run, alignment=alignment, published_note=note, gloss=gloss_run
    )


# A paragraph of prose runs to a few hundred characters, occasionally a couple of
# thousand. Text arriving in blocks far larger than that never came apart into
# paragraphs at all — a PDF whose lines carry no paragraph breaks is the usual
# cause, and no alignment can rescue it.
BLOCK_LIMIT = 6000


def check_usable(chapters: list[Chapter], label: str) -> None:
    """Refuse a book whose text never broke into paragraphs, and name the fix.

    Building anyway yields a reader of a few enormous "paragraphs" running to
    hundreds of pages, set against nothing — worse than an honest refusal.
    """
    paragraphs = [p for chapter in chapters for p in chapter.paragraphs]
    if not paragraphs:
        raise ExtractError(f"{label} has no readable text.")
    lengths = sorted(len(p) for p in paragraphs)
    median = lengths[len(lengths) // 2]
    if median > BLOCK_LIMIT:
        raise ExtractError(
            f"{label} did not come apart into paragraphs: its text arrives in blocks of "
            f"about {median:,} characters, so there is nothing to set beside the other "
            f"book. PDFs often carry no paragraph breaks. An EPUB or plain-text edition "
            f"of the same book will read properly."
        )


def build_positional(
    *,
    title: str,
    chapters: list[Chapter],
    published_chapters: list[Chapter],
    target: Target = ENGLISH,
) -> tuple[str, AlignmentReport]:
    """The free path: no AI, no key. Set a brought published translation beside
    the French by position and render it as the single reading column."""
    check_usable(chapters, "The original")
    check_usable(published_chapters, "The published translation")
    aligned, report = align_published(chapters, published_chapters, None)
    # Render the body only — the same trim the aligner used — so the reader opens
    # on chapter one instead of a title page set beside a blank column.
    body = [c for c in trim_matter(chapters) if c.paragraphs] or chapters
    html = render_html(
        title, body, aligned, published=None,
        published_note=published_note(report), glosses=None, target=target, solo=True,
    )
    return html, report


def build_aligned(
    *,
    title: str,
    chapters: list[Chapter],
    published_chapters: list[Chapter],
    embed: Embed,
    target: Target = ENGLISH,
    on_progress: ProgressFn | None = None,
) -> tuple[str, AlignmentReport]:
    """Set a brought published translation beside the French by *meaning*, using a
    multilingual embedding model, with no translation of our own.

    The cheap-or-free path: the embedding runs on a local Ollama (BGE-M3, free) or a
    cloud model (pennies), and matches the two editions in a shared semantic space —
    so the columns line up even in dialogue and prose that share no words, where the
    surface heuristics could not. The published English is the single reading column.
    """
    check_usable(chapters, "The original")
    check_usable(published_chapters, "The published translation")
    aligned, report = align_published(
        chapters, published_chapters, embed=embed, on_progress=_stage(on_progress, "align")
    )
    body = [c for c in trim_matter(chapters) if c.paragraphs] or chapters
    html = render_html(
        title, body, aligned, published=None,
        published_note=published_note(report), glosses=None, target=target, solo=True,
    )
    return html, report


def published_note(report: AlignmentReport) -> str:
    """Reader-facing note on how the published edition was placed, in the ⓘ
    panel's laconic voice."""
    if report.degraded:
        # Honest before reassuring: when most of the page would be blank, say so
        # and why, rather than promise a column that mostly is not there.
        return (
            f"Only about {round(report.coverage * 100)}% of the French found a "
            "counterpart in this edition — the rest of the page is left blank rather "
            "than guessed. The two editions may be built too differently to line up, "
            "or the file you brought didn't divide into chapters."
        )
    if report.method == "pivot":
        note = (
            "Your translation keeps pace with the French as closely as two editions "
            "allow. It has its own notes and front matter, which stay behind."
        )
    elif report.method == "anchored":
        note = (
            "Your translation is matched to the French by the names and numbers both "
            "editions keep, so it holds its place through the book. Its own notes and "
            "front matter stay behind."
        )
    else:
        return (
            "Your translation is placed beside the French by position, so it can "
            "drift where the two editions differ."
        )
    if report.unmatched:
        note += " A few passages have no counterpart here."
    return note


def _stage(on_progress: ProgressFn | None, stage: str) -> Callable[[int, int], None] | None:
    if on_progress is None:
        return None
    return lambda done, total: on_progress(stage, done, total)
