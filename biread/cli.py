"""Command-line entry point: `python -m biread french.txt`.

Everything the user sees is printed here. The pipeline modules raise; this
decides what that means and which exit code it earns.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .align import align_published
from .cache import Cache
from .cleanup import Chapter, Removal, clean
from .config import Config, load_config
from .errors import BireadError, CacheSchemaError
from .extract import get_extractor
from .gloss import estimate as estimate_gloss
from .gloss import gloss_book
from .llm import get_client
from .export import write_epub
from .render import render_book, slugify
from .translate import estimate, translate_book

PARAGRAPH_LIMIT = 2000
PREVIEW_CHARS = 300
EXAMPLES_SHOWN = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m biread",
        description="Generate a self-contained bilingual (French/English) HTML reader "
                    "from a plain-text book.",
    )
    parser.add_argument("input", type=Path, help="path to the source French text (.txt)")
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("output"),
        help="output directory (default: output/)",
    )
    parser.add_argument(
        "--published", type=Path, default=None,
        help="a published English translation to read side by side with the generated one",
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
        "--gloss", action="store_true",
        help="also annotate the French for hover translation (costs extra; see --dry-run)",
    )
    parser.add_argument(
        "--epub", action="store_true",
        help="also write a reflowable EPUB with the glosses as tap-to-reveal notes",
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


def load_book(path: Path) -> tuple[list[Chapter], list[Removal]]:
    if not path.exists():
        raise BireadError(f"input file not found: {path}")
    return clean(get_extractor(path).extract(path))


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
        label = f"Chapitre {chapter.number}" if chapter.number else "(untitled leading section)"
        title = f' — "{chapter.title}"' if chapter.title else ""
        print(f"  {label}{title}: {len(chapter.paragraphs)} paragraph(s)")

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


def resolve_published(
    path: Path, chapters: list[Chapter], translations: dict[str, str]
) -> tuple[dict[str, str], str]:
    print(f"\nAligning published translation '{path.name}':")
    published_chapters, _ = load_book(path)
    aligned, report = align_published(chapters, published_chapters, translations)

    for note in report.notes:
        print(f"  {note}")

    if report.method == "pivot":
        print("  Matched paragraph by paragraph against the generated translation.")
        # Laconic, in the voice of the other panel — a reader does not need the
        # method, only what to expect from the column in front of them.
        summary = (
            "Your translation keeps pace with the French as closely as two editions "
            "allow. It has its own notes and front matter, which stay behind."
        )
        if report.unmatched:
            summary += " A few passages have no counterpart here."
    else:
        print("  No translation to match against — falling back to position.")
        summary = (
            "Your translation is placed beside the French by position, so it can "
            "drift where the two editions differ."
        )
    return aligned, summary


def report_gloss_estimate(chapters: list[Chapter], cache: Cache, cfg: Config) -> None:
    gloss_cfg = cfg.for_glossing()
    result = estimate_gloss(chapters, cache, gloss_cfg)
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


def run_glossing(chapters: list[Chapter], cache: Cache, cfg: Config):
    gloss_cfg = cfg.for_glossing()

    def progress(done: int, total: int) -> None:
        print(f"\r  glossed {done}/{total} paragraphs…", end="", flush=True)

    print(f"\nGlossing the French with {gloss_cfg.model}:")
    run = gloss_book(chapters, get_client(gloss_cfg), cache, gloss_cfg, progress)
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


def report_estimate(chapters: list[Chapter], cache: Cache, cfg: Config) -> None:
    result = estimate(chapters, cache, cfg)
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


def run_translation(chapters: list[Chapter], cache: Cache, cfg: Config):
    if not cfg.cost_capped:
        print(
            f"Warning: no pricing on file for {cfg.model} — MAX_COST_USD cannot be "
            f"enforced this run. Set PRICE_PER_MTOK in .env to cap it.\n"
        )

    def progress(done: int, total: int) -> None:
        print(f"\r  translated {done}/{total} paragraphs…", end="", flush=True)

    cached = len(cache)
    run = translate_book(chapters, get_client(cfg), cache, cfg, progress)
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
    chapters, removals = load_book(args.input)
    total_paragraphs = sum(len(c.paragraphs) for c in chapters)

    print(f"Cleaned '{args.input.name}':\n")
    report_removals(removals)
    report_structure(chapters)

    title = args.title or humanize(args.input.stem)
    slug = slugify(title)
    cache = open_cache(args.cache_dir / slug / "translations.json", args.rebuild_cache)
    cfg = load_config(require_key=not args.dry_run)

    print()
    if args.dry_run:
        report_estimate(chapters, cache, cfg)
        if args.gloss:
            gloss_cache = open_cache(
                args.cache_dir / slug / "glosses.json", args.rebuild_cache
            )
            report_gloss_estimate(chapters, gloss_cache, cfg)
        return

    if total_paragraphs > PARAGRAPH_LIMIT and not args.force:
        raise BireadError(
            f"{total_paragraphs:,} paragraphs exceeds the {PARAGRAPH_LIMIT:,}-paragraph "
            f"safety limit. Re-run with --force to proceed (this will call the API), or "
            f"use --dry-run to see what it would cost first."
        )

    run_result = run_translation(chapters, cache, cfg)

    # After translating, not before: the generated English is what the published
    # text gets matched against.
    published, published_note = None, ""
    if args.published:
        published, published_note = resolve_published(
            args.published, chapters, run_result.translations
        )

    glosses = None
    if args.gloss:
        gloss_cache = open_cache(args.cache_dir / slug / "glosses.json", args.rebuild_cache)
        glosses = run_glossing(chapters, gloss_cache, cfg).glosses

    output_path = args.output / f"{slug}.html"
    render_book(
        title, chapters, run_result.translations, output_path,
        published, published_note, glosses,
    )
    print(f"\nWrote {output_path}")

    if args.epub:
        epub_path = args.output / f"{slug}.epub"
        write_epub(title, chapters, run_result.translations, glosses, epub_path)
        print(f"Wrote {epub_path}")


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
