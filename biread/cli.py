"""Command-line entry point: `python -m biread french.txt`.

Everything the user sees is printed here. The pipeline modules raise; this
decides what that means and which exit code it earns.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .align import align_published, trim_matter
from .build import check_usable, published_note, recut
from .cache import Cache
from .cleanup import Chapter, Removal, clean
from .config import Config, load_config
from .errors import BireadError, CacheSchemaError
from .extract import get_extractor
from .gloss import estimate as estimate_gloss
from .gloss import gloss_book
from .llm import get_client
from .export import write_epub, write_pdf
from .meta import looks_scanned
from .render import download_name, render_book, slugify
from .segment import unsegmented
from .targets import DEFAULT_LANG, TARGETS, get_target
from .translate import estimate, translate_book

PARAGRAPH_LIMIT = 2000
PREVIEW_CHARS = 300
EXAMPLES_SHOWN = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m biread",
        description="Generate a self-contained bilingual HTML reader (French on the left, "
                    "your chosen language on the right) from a plain-text book.",
    )
    parser.add_argument("input", type=Path, help="path to the source French text (.txt)")
    parser.add_argument(
        "--lang", type=str, default=DEFAULT_LANG, choices=sorted(TARGETS),
        help="target translation language (default: english). Each language is a "
             "fresh translation, built on the key of whoever runs it.",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("output"),
        help="output directory (default: output/)",
    )
    parser.add_argument(
        "--published", type=Path, default=None,
        help="a published translation (in the target language) to read side by side with the generated one",
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=Path("cache"),
        help="where to keep translation caches (default: cache/)",
    )
    parser.add_argument(
        "--title", type=str, default=None,
        help="book title for the reader header (default: derived from the filename)",
    )
    parser.add_argument(
        "--author", type=str, default=None,
        help="the book's author, written into the EPUB metadata and the PDF title page",
    )
    parser.add_argument(
        "--gloss", action="store_true",
        help="also annotate the French for hover translation (costs extra; see --dry-run)",
    )
    parser.add_argument(
        "--revise", action="store_true",
        help="let a reader correct the AI translation in the reader — by hand, or "
             "rewritten on their own API key (never yours; nothing is called at build)",
    )
    parser.add_argument(
        "--builder-url", type=str, default="", metavar="URL",
        help="where this book's reader can cross to the builder, as a quiet corner "
             "arrow. Omit it and no arrow is shown, so a book you share never points "
             "at nothing",
    )
    parser.add_argument(
        "--epub", action="store_true",
        help="also write a fixed-layout EPUB: the French and English as a locked "
             "spread, like the reader (needs the browser engine, as --pdf does)",
    )
    parser.add_argument(
        "--pdf", action="store_true",
        help="also write a print PDF, French and English side by side (needs the [browser] extra)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report what is uncached and an estimated cost, then exit without calling the API",
    )
    parser.add_argument(
        "--force", action="store_true",
        help=f"proceed with books above {PARAGRAPH_LIMIT:,} paragraphs",
    )
    parser.add_argument(
        "--rebuild-cache", action="store_true",
        help="discard a cache written by an incompatible version instead of asking",
    )
    return parser


def humanize(stem: str) -> str:
    words = [w for w in re.split(r"[-_]+", stem) if w]
    return " ".join(w[:1].upper() + w[1:] for w in words) or stem


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def load_book(path: Path) -> tuple[list[Chapter], list[Removal], bool]:
    """The book, what was stripped from it, and whether the file is a scan."""
    if not path.exists():
        raise BireadError(f"input file not found: {path}")
    raw = get_extractor(path).extract(path)
    chapters, removals = clean(raw, from_pdf=path.suffix.lower() == ".pdf")
    return chapters, removals, looks_scanned(path, raw)


def report_scan(names: list[str]) -> None:
    """Say a file is a photograph of a book, once, before anything is paid for.

    Terminal only, like every other figure that would clutter a page someone is
    reading. What it is for is the decision in front of the reader: OCR misreads
    words, biread does not correct them because correcting them means writing
    into the book, and a second edition of the same title usually reads clean.
    """
    if not names:
        return
    print(f"\n{' and '.join(names)} arrived as a scan: an image of every page, with "
          f"the text read off it by OCR. Expect misread words in that column "
          f"(`lloquentin` for Roquentin, `itwas`, a quotation mark read as a page "
          f"number). They are left exactly as the file has them, because correcting "
          f"them would mean writing words into the book that its author did not. A "
          f"digital edition of the same title reads clean.")


def report_removals(removals: list[Removal]) -> None:
    if not removals:
        print("Nothing recognized as boilerplate — kept the file as-is.")
        return
    groups: dict[str, list[str]] = {}
    for removal in removals:
        groups.setdefault(removal.kind, []).append(removal.detail)
    print(f"Stripped {len(removals)} item(s):")
    for kind, details in groups.items():
        print(f"  {kind} ({len(details)}):")
        for detail in details[:EXAMPLES_SHOWN]:
            print(f"    {truncate(detail, 70)}")
        if len(details) > EXAMPLES_SHOWN:
            print(f"    … and {len(details) - EXAMPLES_SHOWN} more")


def report_structure(chapters: list[Chapter]) -> None:
    total = sum(len(c.paragraphs) for c in chapters)
    print(f"\nDetected {len(chapters)} chapter(s), {total} paragraph(s) total:")
    for chapter in chapters:
        # A diary's entries carry a title and no number, and calling those
        # "untitled" printed `(untitled leading section) — "MARDI 30 JANVIER."`
        # twenty-one times down a build of Nausea.
        if chapter.number:
            label = f'Chapitre {chapter.number}{f" — {chapter.title}" if chapter.title else ""}'
        else:
            label = chapter.title or "(untitled leading section)"
        print(f"  {label}: {len(chapter.paragraphs)} paragraph(s)")

    first = next((c for c in chapters if c.paragraphs), None)
    if first:
        print(f"\nFirst paragraph, as rejoined:\n  {truncate(first.paragraphs[0], PREVIEW_CHARS)}")


def open_cache(path: Path, rebuild: bool) -> Cache:
    try:
        return Cache.load(path)
    except CacheSchemaError as e:
        if rebuild:
            print(f"Rebuilding incompatible cache at {e.path}.")
            return Cache.rebuild(e.path)
        print(f"\n{e}", file=sys.stderr)
        if not sys.stdin.isatty():
            raise BireadError(
                "Re-run with --rebuild-cache to discard it and start over."
            ) from e
        if input("Rebuild this cache from scratch? [y/N] ").strip().lower() != "y":
            raise BireadError("Aborted — cache left untouched.") from e
        return Cache.rebuild(e.path)


def cache_file(cache_dir: Path, slug: str, base: str, target) -> Path:
    """Where a book's translation/gloss cache lives. English keeps the original
    filename, so books built before --lang existed do not re-translate; every
    other language gets its own file beside it, keyed by code."""
    name = f"{base}.json" if target.key == DEFAULT_LANG else f"{base}.{target.code}.json"
    return cache_dir / slug / name


def resolve_published(
    path: Path, published_chapters: list[Chapter], chapters: list[Chapter],
    translations: dict[str, str]
) -> tuple[dict[str, str], str]:
    print(f"\nAligning published translation '{path.name}':")
    aligned, report = align_published(chapters, published_chapters, translations)

    for note in report.notes:
        print(f"  {note}")

    method_line = {
        "pivot": "Matched paragraph by paragraph against the generated translation.",
        "anchored": "Matched on the names and numbers both editions share.",
    }.get(report.method, "No translation to match against — falling back to position.")
    print(f"  {method_line}")

    if report.total:
        print(f"  Coverage: {report.total - report.unmatched}/{report.total} "
              f"French paragraphs matched ({round(report.coverage * 100)}%).")
    if report.degraded:
        print("  ⚠ Alignment is degraded: most of the published column will be blank. "
              "The two editions may be structured too differently to line up, or the "
              "published file did not divide into chapters. The reader says so too.")

    return aligned, published_note(report)


def report_gloss_estimate(chapters: list[Chapter], cache: Cache, cfg: Config,
                          gloss_lang: str = "English") -> None:
    gloss_cfg = cfg.for_glossing()
    result = estimate_gloss(chapters, cache, gloss_cfg, gloss_lang)
    print(f"\nGlossing: {result.cached} of {result.total} paragraph(s) already annotated.")
    if not result.pending:
        print("Nothing left to gloss.")
        return
    print(f"Would gloss {result.pending} paragraph(s) with {gloss_cfg.model}.")
    if result.cost is None:
        print(f"No pricing on file for {gloss_cfg.model} — its spend cannot be capped.")
    else:
        print(f"Estimated cost of a clean pass: ${result.cost:.4f}. Paragraphs the "
              f"model mis-segments are retried on their own, which on difficult text "
              f"has run to roughly double this — read it as a floor, not a ceiling.")


def run_glossing(chapters: list[Chapter], cache: Cache, cfg: Config, gloss_lang: str = "English"):
    gloss_cfg = cfg.for_glossing()

    def progress(done: int, total: int) -> None:
        print(f"\r  glossed {done}/{total} paragraphs…", end="", flush=True)

    print(f"\nGlossing the French with {gloss_cfg.model}:")
    run = gloss_book(chapters, get_client(gloss_cfg), cache, gloss_cfg, progress, gloss_lang)
    if run.glossed:
        print()
        if run.rescued:
            print(f"  {run.rescued} needed a second pass on their own.")
    else:
        print("Every paragraph was already annotated — nothing to gloss.")

    if run.stopped_at_cap:
        print(f"\nStopped: spent an estimated ${run.cost:.4f}, at or above your "
              f"MAX_COST_USD cap (${gloss_cfg.max_cost_usd:.2f}). Annotated so far is "
              f"cached — raise the cap and re-run to continue.")
    elif run.cost is not None:
        print(f"Gloss cost this run: ${run.cost:.4f}")

    if run.unglossed:
        print(f"\n{len(run.unglossed)} paragraph(s) could not be annotated and stay "
              f"plain — the model's segmentation did not match the source text:")
        for text in run.unglossed[:EXAMPLES_SHOWN]:
            print(f"  {truncate(text, 70)}")
        if len(run.unglossed) > EXAMPLES_SHOWN:
            print(f"  … and {len(run.unglossed) - EXAMPLES_SHOWN} more")
    return run


def report_estimate(chapters: list[Chapter], cache: Cache, cfg: Config,
                    target_name: str = "English") -> None:
    result = estimate(chapters, cache, cfg, target_name)
    print(f"Translation: {result.cached} of {result.total} paragraph(s) already cached.")
    if not result.pending:
        print("Nothing left to translate.")
        return

    print(f"Would translate {result.pending} paragraph(s) with {cfg.model}.")
    if result.cost is None:
        print(
            f"No pricing on file for {cfg.model}, so MAX_COST_USD cannot be enforced.\n"
            f"Set PRICE_PER_MTOK=<input>,<output> in .env to cap this model's spend."
        )
        return
    print(
        f"Rough estimated cost: ${result.cost:.4f} "
        f"(character-count heuristic, not a tokenizer — treat it as a ballpark)"
    )
    if result.cost > cfg.max_cost_usd:
        print(
            f"That is above your MAX_COST_USD cap (${cfg.max_cost_usd:.2f}), so a real run "
            f"would stop partway through. Raise the cap in .env to go further in one pass."
        )


def run_translation(chapters: list[Chapter], cache: Cache, cfg: Config, target_name: str = "English"):
    if not cfg.cost_capped:
        print(
            f"Warning: no pricing on file for {cfg.model} — MAX_COST_USD cannot be "
            f"enforced this run. Set PRICE_PER_MTOK in .env to cap it.\n"
        )

    def progress(done: int, total: int) -> None:
        print(f"\r  translated {done}/{total} paragraphs…", end="", flush=True)

    cached = len(cache)
    run = translate_book(chapters, get_client(cfg), cache, cfg, progress, target_name)
    if run.translated:
        print()
    else:
        print(f"Every paragraph was already cached ({cached}) — nothing to translate.")

    if run.stopped_at_cap:
        print(
            f"\nStopped: spent an estimated ${run.cost:.4f}, at or above your MAX_COST_USD "
            f"cap (${cfg.max_cost_usd:.2f}). Everything translated so far is cached — raise "
            f"the cap in .env and re-run to continue where this left off."
        )
    elif run.cost is not None:
        print(f"Translation cost this run: ${run.cost:.4f}")

    missing = run.total - len(run.translations)
    if missing:
        print(f"Note: {missing} paragraph(s) are still untranslated and will render empty.")
    return run


def run(args: argparse.Namespace) -> None:
    chapters, removals, scanned = load_book(args.input)
    # Both files are read before either is judged: where one lost its paragraph
    # breaks and the other kept them, the other's shape is what puts them back,
    # and a refusal issued file by file would never find that out.
    published_chapters = None
    scans = [args.input.name] if scanned else []
    if args.published:
        published_chapters, _, published_scanned = load_book(args.published)
        if published_scanned:
            scans.append(args.published.name)
    chapters, published_chapters, cut = recut(chapters, published_chapters)
    # A side still flat has no other edition to take its breaks from, and the
    # model can read it for them at build time — so it is refused here only when
    # no build is going to happen. Refusing a file the next command would repair
    # is the kind of no a tool should not give.
    flat = [name for name, book in (
        (args.input.name, chapters),
        (args.published.name if args.published else "", published_chapters),
    ) if book is not None and unsegmented(book)]
    if flat and args.dry_run:
        print(f"\n{' and '.join(flat)} arrived with no paragraph breaks and no other "
              f"edition to take them from. The build reads the text for them on the "
              f"model, at roughly a third of what translating it costs. Nothing here "
              f"calls the API; re-run without --dry-run to build it.")
    elif not flat:
        check_usable(chapters, "The book", args.input.name)
        if published_chapters is not None:
            check_usable(published_chapters, "The published translation", args.published.name)
    if cut:
        recut_chapters = published_chapters if cut == "published" else chapters
        print(f"\nThe {cut} edition arrived with no paragraph breaks. Cut to the other "
              f"edition's shape: {sum(len(c.paragraphs) for c in recut_chapters):,} paragraphs.")

    report_scan(scans)

    print(f"Cleaned '{args.input.name}':\n")
    report_removals(removals)
    report_structure(chapters)

    # From here the book is its body only: the title page, table of contents and
    # licence that bracket it are dropped, so the reader opens on chapter one and
    # no front matter is translated or set beside a blank. Same trim the aligner
    # applies, kept in step so what is read is what was aligned.
    chapters = [c for c in trim_matter(chapters) if c.paragraphs] or chapters
    total_paragraphs = sum(len(c.paragraphs) for c in chapters)

    title = args.title or humanize(args.input.stem)
    author = args.author or ""
    slug = slugify(title)
    target = get_target(args.lang)
    cache = open_cache(cache_file(args.cache_dir, slug, "translations", target), args.rebuild_cache)
    cfg = load_config(require_key=not args.dry_run)

    print()
    if args.dry_run:
        report_estimate(chapters, cache, cfg, target.name)
        if args.gloss:
            gloss_cache = open_cache(
                cache_file(args.cache_dir, slug, "glosses", target), args.rebuild_cache
            )
            report_gloss_estimate(chapters, gloss_cache, cfg, target.name)
        return

    if total_paragraphs > PARAGRAPH_LIMIT and not args.force:
        raise BireadError(
            f"{total_paragraphs:,} paragraphs exceeds the {PARAGRAPH_LIMIT:,}-paragraph "
            f"safety limit. Re-run with --force to proceed (this will call the API), or "
            f"use --dry-run to see what it would cost first."
        )

    run_result = run_translation(chapters, cache, cfg, target.name)

    # After translating, not before: the generated translation is what the
    # published text gets matched against.
    published, published_note = None, ""
    if args.published:
        published, published_note = resolve_published(
            args.published, published_chapters, chapters, run_result.translations
        )

    glosses = None
    if args.gloss:
        gloss_cache = open_cache(cache_file(args.cache_dir, slug, "glosses", target), args.rebuild_cache)
        glosses = run_glossing(chapters, gloss_cache, cfg, target.name).glosses

    # The HTML keeps the slug so its hosted URL stays clean; the EPUB and PDF are
    # named for the book, since those are the files a reader saves and shares.
    # They are written first so the reader can embed them behind its download
    # control — the book stays one self-contained, shareable file.
    #
    # When a published translation is present, each format is built twice — once
    # from the AI translation, once from the published one (published where it
    # matches, AI where it doesn't, exactly as the reader's "Published" view). The
    # download then hands over whichever edition the reader has open. With no
    # published translation there is only the one edition, named plainly.
    editions = [("translation", run_result.translations, "")]
    if published:
        published_column = {**run_result.translations,
                            **{k: v for k, v in published.items() if v}}
        editions = [("translation", run_result.translations, " (AI translation)"),
                    ("published", published_column, " (published translation)")]

    downloads = []
    for source, column, marker in editions:
        # A fixed-layout spread with no glosses — the French left, the translation
        # right, like the reader. Both formats measure the type in headless
        # Chromium, so they need the browser engine. The book's own title stays on
        # the page; the marker only distinguishes the saved files.
        name = download_name(f"{title}{marker}")
        if args.epub:
            epub_path = args.output / f"{name}.epub"
            write_epub(title, chapters, column, epub_path, target, author)
            print(f"Wrote {epub_path}")
            downloads.append(("epub", source, epub_path.name, epub_path.read_bytes()))
        if args.pdf:
            pdf_path = args.output / f"{name}.pdf"
            write_pdf(title, chapters, column, pdf_path, target, author)
            print(f"Wrote {pdf_path}")
            downloads.append(("pdf", source, pdf_path.name, pdf_path.read_bytes()))

    # --revise ships the reader a way to correct the translation on the reader's
    # own key; the build only records which model that would be, never a key or a
    # cost. English content stays byte-identical, so this does not touch the cache.
    revise = None
    if args.revise:
        revise = {"provider": cfg.provider, "model": cfg.model, "target": target.name}

    output_path = args.output / f"{slug}.html"
    render_book(
        title, chapters, run_result.translations, output_path,
        published, published_note, glosses, downloads, target, revise,
        builder_url=args.builder_url,
    )
    print(f"\nWrote {output_path}")
    if args.revise:
        print("Readers can correct the translation with their own key — see the ⓘ note.")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except BireadError as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted — cached work is kept; re-run to continue.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
