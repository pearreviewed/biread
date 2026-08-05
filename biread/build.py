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
from pathlib import Path
from typing import Callable

from .align import AlignmentReport, Embed, align_published, trim_matter
from .cache import Cache
from .cleanup import Chapter
from .config import Config
from .errors import ExtractError
from .gloss import GlossRun, gloss_book
from .llm import LLMClient
from .render import render_html
from .segment import BLOCK_LIMIT, segment_like, unsegmented
from .targets import ENGLISH, Target
from .translate import BatchFn, TranslationRun, translate_book

#: (stage, done, total); stage is "translate" or "gloss".
ProgressFn = Callable[[str, int, int], None]


@dataclass
class BuildResult:
    html: str
    #: None on the aligned path, which sets an edition the reader owns beside the
    #: original and translates nothing of its own.
    translation: TranslationRun | None = None
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
    chapters, published_chapters, cut = recut(chapters, published_chapters)
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
        alignment.cut = cut
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


# What to bring instead, by the format that lost the breaks. A word processor is
# named separately from a PDF because it is almost always the *second* format a
# book has been through — a PDF saved as .docx keeps every word and none of the
# paragraph marks — and the fix is the file it was made from, which the reader
# still has. Anything else is asked for an edition that sets its paragraphs apart.
CONVERSION_ADVICE = {
    ".docx": "A Word file converted from a PDF keeps every word and loses every "
             "paragraph mark. The PDF or EPUB it was made from will read properly.",
    ".doc": "A Word file converted from a PDF keeps every word and loses every "
            "paragraph mark. The PDF or EPUB it was made from will read properly.",
    ".rtf": "A word-processor file converted from a PDF keeps every word and loses "
            "every paragraph mark. The PDF or EPUB it was made from will read properly.",
    ".pdf": "A PDF sometimes carries no paragraph breaks at all. An EPUB or "
            "plain-text edition of the same book will read properly.",
}
DEFAULT_ADVICE = ("An EPUB, or a plain-text edition with a blank line between its "
                  "paragraphs, will read properly.")


def recut(
    chapters: list[Chapter], published_chapters: list[Chapter] | None
) -> tuple[list[Chapter], list[Chapter] | None, str]:
    """Where one edition lost its paragraph breaks and the other kept them, cut it
    to the other's shape rather than refusing the book.

    Only where exactly one side is flat: two flat editions have nothing to cut
    against, and refusing is then the honest answer. Which side was cut comes back
    out, because a book whose paragraphing on one side came off the other edition
    has to say so.
    """
    if published_chapters is None:
        return chapters, None, ""
    flat_original = unsegmented(chapters)
    flat_published = unsegmented(published_chapters)
    if flat_published and not flat_original:
        return chapters, segment_like(published_chapters, chapters), "published"
    if flat_original and not flat_published:
        return segment_like(chapters, published_chapters), published_chapters, "original"
    return chapters, published_chapters, ""


def check_usable(chapters: list[Chapter], label: str, source: str | None = None) -> None:
    """Refuse a book whose text never broke into paragraphs, and name the fix.

    Building anyway yields a reader of a few enormous "paragraphs" running to
    hundreds of pages, set against nothing — worse than an honest refusal.

    `source` is the file's own name where the caller knows it, which is what the
    reader needs when two files are in play and only one of them is at fault; the
    advice is picked from its format rather than blamed on PDFs whatever arrived.
    """
    paragraphs = [p for chapter in chapters for p in chapter.paragraphs]
    if not paragraphs:
        raise ExtractError(f"{source or label} has no readable text.")
    lengths = sorted(len(p) for p in paragraphs)
    median = lengths[len(lengths) // 2]
    if median > BLOCK_LIMIT:
        suffix = Path(source).suffix.lower() if source else ""
        shape = (f"as one unbroken block of about {median:,} characters"
                 if len(paragraphs) == 1 else
                 f"in blocks of about {median:,} characters")
        raise ExtractError(
            f"{source or label} did not come apart into paragraphs: it arrives {shape}, "
            f"so there is nothing to translate a paragraph at a time or to set beside "
            f"another book. {CONVERSION_ADVICE.get(suffix, DEFAULT_ADVICE)}"
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
    chapters, published_chapters, cut = recut(chapters, published_chapters)
    check_usable(chapters, "The original")
    check_usable(published_chapters, "The published translation")
    aligned, report = align_published(chapters, published_chapters, None)
    report.cut = cut
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
    gloss: bool = False,
    gloss_client: LLMClient | None = None,
    gloss_cache: Cache | None = None,
    gloss_cfg: Config | None = None,
    on_progress: ProgressFn | None = None,
) -> BuildResult:
    """Set a brought published translation beside the French by *meaning*, using a
    multilingual embedding model, with no translation of our own.

    The cheap-or-free path: the embedding runs on a local Ollama (BGE-M3, free) or a
    cloud model (pennies), and matches the two editions in a shared semantic space —
    so the columns line up even in dialogue and prose that share no words, where the
    surface heuristics could not. The published English is the single reading column.

    Glossing is separate work on a chat model, so it needs a client and a config of
    its own; the embedding key usually reaches one. Without them the book reads the
    same, minus the hover.
    """
    chapters, published_chapters, cut = recut(chapters, published_chapters)
    check_usable(chapters, "The original")
    check_usable(published_chapters, "The published translation")
    aligned, report = align_published(
        chapters, published_chapters, embed=embed, on_progress=_stage(on_progress, "align")
    )
    report.cut = cut
    # Render the body only — the same trim the aligner used — and gloss exactly what
    # is rendered, so no call is paid for on a paragraph the reader never sees.
    body = [c for c in trim_matter(chapters) if c.paragraphs] or chapters

    gloss_run = None
    if gloss and gloss_client is not None and gloss_cfg is not None:
        gloss_run = gloss_book(
            body,
            gloss_client,
            gloss_cache if gloss_cache is not None else Cache(None),
            gloss_cfg,
            _stage(on_progress, "gloss"),
            target.name,
        )

    note = published_note(report)
    html = render_html(
        title, body, aligned, published=None, published_note=note,
        glosses=gloss_run.glosses if gloss_run else None, target=target, solo=True,
    )
    return BuildResult(html=html, alignment=report, published_note=note, gloss=gloss_run)


def published_note(report: AlignmentReport) -> str:
    """Reader-facing note on how the published edition was placed, in the ⓘ
    panel's laconic voice."""
    return _placement_note(report) + cut_note(report)


def _placement_note(report: AlignmentReport) -> str:
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


def cut_note(report: AlignmentReport) -> str:
    """Said whenever one side's paragraphing is not its own.

    The reader is looking at breaks that came off the other edition, and there is
    no way to see that from the page. Worth a sentence of the ⓘ panel's room.
    """
    if report.cut == "published":
        return (" The edition you brought arrived with its paragraph breaks lost, so it "
                "is divided here to follow the original's paragraphs.")
    if report.cut == "original":
        return (" The original arrived with its paragraph breaks lost, so it is divided "
                "here to follow the translation's paragraphs.")
    return ""


def _stage(on_progress: ProgressFn | None, stage: str) -> Callable[[int, int], None] | None:
    if on_progress is None:
        return None
    return lambda done, total: on_progress(stage, done, total)
