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

from .align import AlignmentReport, align_published
from .cache import Cache
from .cleanup import Chapter
from .config import Config
from .gloss import GlossRun, gloss_book
from .llm import LLMClient
from .render import render_html
from .targets import ENGLISH, Target
from .translate import TranslationRun, translate_book

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
) -> BuildResult:
    run = translate_book(chapters, client, cache, cfg, _stage(on_progress, "translate"), target.name)

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


def build_positional(
    *,
    title: str,
    chapters: list[Chapter],
    published_chapters: list[Chapter],
    target: Target = ENGLISH,
) -> tuple[str, AlignmentReport]:
    """The free path: no AI, no key. Set a brought published translation beside
    the French by position and render it as the single reading column."""
    aligned, report = align_published(chapters, published_chapters, None)
    html = render_html(
        title, chapters, aligned, published=None,
        published_note=published_note(report), glosses=None, target=target, solo=True,
    )
    return html, report


def published_note(report: AlignmentReport) -> str:
    """Reader-facing note on how the published edition was placed, in the ⓘ
    panel's laconic voice."""
    if report.method == "pivot":
        note = (
            "Your translation keeps pace with the French as closely as two editions "
            "allow. It has its own notes and front matter, which stay behind."
        )
        if report.unmatched:
            note += " A few passages have no counterpart here."
        return note
    return (
        "Your translation is placed beside the French by position, so it can "
        "drift where the two editions differ."
    )


def _stage(on_progress: ProgressFn | None, stage: str) -> Callable[[int, int], None] | None:
    if on_progress is None:
        return None
    return lambda done, total: on_progress(stage, done, total)
