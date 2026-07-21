# Architecture

biread is a **linear pipeline**: a plain-text book goes in one end, a
self-contained bilingual HTML reader comes out the other, and every stage in
between is one module with one job. If you read `cli.run()`, you've read the
table of contents — it calls the stages in order. This file is the map for
someone opening the repo for the first time, and for anyone who wants to add a
book, a format, or a language.

## The pipeline

```
extract/       a source file        →  raw text
cleanup.py     raw text             →  chapters of clean paragraphs
translate.py   paragraphs           →  English, batched and cached
align.py       a published edition  →  matched to the French by content   (optional, --published)
gloss.py       paragraphs           →  hover units                        (optional, --gloss)
render/        the assembled book   →  one self-contained HTML file
export/        the assembled book   →  EPUB / PDF                          (optional, --epub / --pdf)
```

Supporting cast, not stages: `cache.py` (content-hash JSON cache), `config.py`
(provider, model, spend cap, read from `.env`), `llm/` (one thin client per
provider behind a shared interface), `language.py` (what glossing needs to know
about the source language), and `errors.py` (the exceptions the CLI turns into
exit codes).

Only two stages cost money — `translate.py` and `gloss.py`, because only they
call a model. Everything else is pure transformation of text you already have,
which is why `--dry-run`, the exports, and re-rendering are all free. Every
language is self-serve: a book in a non-default `--lang` is a fresh translation,
so the reader who would like one builds it from the same French source on their
own key. Each edition is created, and paid for, by whoever wants it.

## How the stages fit

- **`extract/`** — file → raw string, and nothing more. One `Extractor`
  subclass per file type, registered in `EXTRACTORS`; `.txt` is the only one so
  far. Stripping and structure happen downstream, so a new format is a small,
  isolated addition.
- **`cleanup.py`** — strips Project Gutenberg and Wikisource boilerplate,
  rejoins hard-wrapped lines into real paragraphs, and splits the result into
  chapters. Everything it removes is *reported back*, so a new source shows you
  what it ate instead of losing text silently.
- **`translate.py`** — batches paragraphs into one request with `@@@N@@@`
  markers, caches each result by content hash, and merges on write so two runs
  can't clobber each other. The English is treated as the primary reading text,
  not a literal crib.
- **`align.py`** — pairs a published translation you own to the French *by
  content*, pivoting through the generated English (English-to-English), because
  a translator splits and merges paragraphs and a published edition carries
  front matter the source lacks. Positional pairing was tried first and was
  wrong; see the Reversals in `CLAUDE.md`.
- **`gloss.py`** — asks the model to divide a paragraph into hover units and
  explain each in context, then treats the answer as a *proposal*: every unit is
  located in the real paragraph and only its character offsets are kept, so a
  model that rewrites a word can never put its version in front of a reader. The
  width rule (one noun or verb per hover) is applied at render, not baked into
  the cache, so it can be retuned without paying to gloss again.
- **`render/`** — inlines the fonts and paper texture, serialises the book to
  JSON, and substitutes both into `reader.{html,css,js}`. Pagination is **not**
  here — it happens in the browser at runtime, against the real page box.
- **`export/`** — `epub.py` (reflowable, glosses as tap-to-reveal notes, built
  with the standard library) and `pdf.py` (fixed two-column print, headless
  Chromium). Both reuse the same in-memory book; neither calls the API.

## Three things worth knowing early

- **The output is one file.** No server, no network, no build step at read time
  — fonts, images, book data, and (with `--epub`/`--pdf`) the downloads are all
  inlined. You can email it.
- **The cache is the expensive, rebuildable asset.** Keyed by content hash, so
  re-running a finished book costs nothing and editing one paragraph re-fetches
  only that paragraph. It's plain JSON under `cache/<book>/`; back it up by
  copying the directory.
- **The reader is plain files.** `reader.{html,css,js}` in
  `render/templates/`, edited as plain files — no bundler. `render/` only inlines
  assets and substitutes the book data. Pagination, the hover glosses, the
  save/share-by-URL, and the download menu all live in `reader.js`.

## Adding a book

A different **French** book works today: point biread at any `.txt` and the
whole pipeline runs, with its own cache directory by slug and its own (paid)
translation pass. Two limits to know:

- The extractor only handles `.txt`. Another format is one `Extractor` subclass.
- Chapters are found by `CHAPTER_RE` in `cleanup.py`, which matches
  `CHAPITRE N` / `CHAPTER N` headings. A book that divides itself differently
  (`Livre premier`, a bare `I.`) lands as one chapter until that pattern learns
  the new shape. Cleanup reports what it stripped, so check that report on a new
  source.

## Adding a language

Two directions, at different stages of done.

**The target — shipped.** `--lang` builds a book into any language in
`targets.py`. A `Target` row carries the language's name (for the prompts), its
hyphenation code, its chapter word, and the reader's whole UI table;
`translate.py`, `gloss.py`, `render/`, and the exports read the target through
it, and the cache is kept per-language so switching does not collide. English is
the default and renders byte-for-byte as before, so old books do not re-translate;
adding French → German is one row. The *Lecteur bilingue* masthead is
deliberately left French, as the reader's signature — everything else follows
the target.

**The source — still French.** The harder half, the linguistics of glossing, is
already parameterised and is the worked example for the rest. `language.py`
defines a `Language` (its `function_words`, `coordinators`, `prepositions`, and
the language-specific half of the gloss prompt), and `gloss.py` reads everything
through that one object. Adding `GERMAN = Language(...)` makes the glossing stage
reason in German — no code change, just the table.

What still assumes a French *source*, three places:

1. **`gloss.py`** selects the source with a literal
   `from .language import FRENCH as LANGUAGE` — that should become a choice, not
   an import.
2. **`translate.py`**'s prompt names "French" as the source and reasons about
   *tu/vous*; the source wants to be a parameter the way the target already is.
3. **`cleanup.py`**'s `CHAPTER_RE` and its Wikisource strings (`Ajouter des
   langues`, `Télécharger`) are French-specific, and `render/` still hardcodes
   the `Chapitre {n}` eyebrow and `lang="fr"` on the source column.

Same move as the target, one direction over.
