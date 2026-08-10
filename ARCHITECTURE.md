# Architecture

biread is a **linear pipeline**: a plain-text book goes in one end, a
self-contained bilingual HTML reader comes out the other, and every stage in
between is one module with one job. If you read `cli.run()`, you've read the
table of contents — it calls the stages in order. This file is the map for
someone opening the repo for the first time, and for anyone who wants to add a
book, a format, or a language.

## The pipeline

```
extract/       a source file        →  raw text          (.txt .epub .pdf .html .docx)
normalize.py   raw text             →  raw text repaired: the injuries an
                                       extractor inflicts, undone first
cleanup.py     raw text             →  chapters of clean paragraphs
segment.py     a flattened edition  →  paragraph breaks put back           (when needed)
notes.py       chapters             →  footnotes removed where corroborated
spacing.py     a scan's chapters    →  words an OCR ran together, split    (optional, --respace)
translate.py   paragraphs           →  the target language, batched and cached
align.py       a published edition  →  matched to the French by meaning    (optional, --published)
gloss.py       paragraphs           →  hover units                         (optional, --gloss)
render/        the assembled book   →  one self-contained HTML file
export/        the assembled book   →  EPUB / PDF                          (optional, --epub / --pdf)
```

The four stages between extract and translate are the **repair layer**, and they
exist because a real book arrives damaged. Their shared rule is that a repair
must be corroborated by the file itself rather than inferred from shape: that is
what keeps them inert on a clean source, which is measured against the whole
example corpus rather than argued.

Supporting cast, not stages: `cache.py` (content-hash JSON cache, with an
`on_write` hook so the browser can persist without a filesystem), `config.py`
(provider, model, spend cap, read from `.env`), `llm/` (one thin client per
provider behind a shared interface), `language.py` (what glossing needs to know
about the source language), `targets.py` (one row per target language),
`build.py` (the pipeline shared by the CLI and the in-browser builder), and
`errors.py` (the exceptions the CLI turns into exit codes).

Beside the pipeline sit the library modules, which fetch books rather than
transform them — `wikisource.py` and `standardebooks.py` resolve and fetch two
editions, `shelf.py` holds the curated records, and `publish.py`, `check.py` and
`formats.py` are the commands that turn a shelf record into a file somebody has
looked at and approved.

Only two stages cost money — `translate.py` and `gloss.py`, because only they
call a model. Everything else is pure transformation of text you already have,
which is why `--dry-run`, the exports, and re-rendering are all free. Every
language is self-serve: a book in a non-default `--lang` is a fresh translation,
so the reader who would like one builds it from the same French source on their
own key. Each edition is created, and paid for, by whoever wants it.

## How the stages fit

- **`extract/`** — file → raw string, and nothing more. One `Extractor`
  subclass per file type, registered in `EXTRACTORS`: `.txt`, `.epub`, `.pdf`,
  `.html` and `.docx`. Stripping and structure happen downstream, so a new
  format is a small, isolated addition.
- **`normalize.py`** — undoes what an extractor does to a page before anything
  tries to read it: whitespace runs, words hyphenated across a line break,
  running headers and bare page numbers, a heading word marooned from its
  numeral. It also reads a scan's *indentation* to find where paragraphs begin,
  which is the compositor speaking where everything else here is inference.
- **`segment.py`** — an edition whose paragraph breaks were lost in conversion.
  Where a second edition is in play, the flat one is cut to that one's shape by
  proportion, which is free and needs no model; where there is not, the model is
  shown numbered sentences and answers with numbers, so it never handles the
  text at all.
- **`notes.py`** — removes footnotes and their markers only where the prose
  refers to them, or where they form the numbered run closing a chapter. An
  uncorroborated candidate is left in: a note left in is untidy, a deleted
  sentence is silent and unrecoverable.
- **`spacing.py`** — `--respace` only, and for scans only. What is kept from the
  model's reply is not its text but *where it put the spaces*: the reply is
  walked against the original character by character and the passage rebuilt
  from the original's own characters, so a reply that rewrites a word stops
  aligning and is discarded whole.
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
  front matter the source lacks. Two editions share meaning rather than words, so
  this is a job for a model, not for token overlap — either the generated
  translation as a pivot (the CLI's path, so alignment runs after `translate.py`)
  or an `embed` function that matches the two editions directly in a shared
  multilingual space, with no translation of its own (the web builder's path).
  Positional pairing was tried first and was wrong; see the Reversals in
  `CLAUDE.md`.
- **`gloss.py`** — asks the model to divide a paragraph into hover units and
  explain each in context, then treats the answer as a *proposal*: every unit is
  located in the real paragraph and only its character offsets are kept, so a
  model that rewrites a word can never put its version in front of a reader. The
  width rule (one noun or verb per hover) is applied at render, not baked into
  the cache, so it can be retuned without paying to gloss again.
- **`render/`** — inlines the fonts and paper texture, serialises the book to
  JSON, and substitutes both into `reader.{html,css,js}`. Pagination is **not**
  here — it happens in the browser at runtime, against the real page box.
- **`export/`** — `epub.py` (a fixed-layout spread, French left / English right,
  paginated in headless Chromium with the reader's own algorithm; no glosses) and
  `pdf.py` (fixed two-column print, also headless Chromium). Both reuse the same
  in-memory book and need the `[browser]` extra; neither calls the API. Beside
  them, `refit.py` reads a finished book back **out of its own page**, so a
  format can be made long after the build and without paying for it twice —
  which is what lets a book built in the browser, where no Chromium can run, be
  given its EPUB later by `python -m biread.formats`.

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
  assets and substitutes the book data (and, with `--revise`, which provider a
  reader's own key would call — never a key, never a cost). Pagination, the hover
  glosses, the save/share-by-URL, the download menu, and reader-side correction
  all live in `reader.js`.

## Adding a book

A different **French** book works today: point biread at any `.txt`, `.epub`,
`.pdf`, `.html` or `.docx` and the whole pipeline runs, with its own cache
directory by slug and its own (paid) translation pass.

Chapters are found in four ways, tried in that order, and each later one is a
last resort reached only when the earlier found nothing: `CHAPTER_RE` for a
written-out `CHAPITRE N` / `CHAPTER N`; a run of bare numerals, which must step
by one oftener than not *and* have a sentence beginning under each, since a
clean scan's page folios satisfy every other test; dated headings, for a book
divided by day rather than by number; and otherwise the book stands as one
section, because ascending numbers are not a spine.

Cleanup reports everything it removes, so the thing to do on a new source is
read that report. The failure that costs most is not a missed heading but a
wrong one: `trim_matter` cuts to the first numbered chapter, so a false heading
early in a file can delete the book in front of it. It refuses to drop a leading
section worth more than a quarter of the file for exactly that reason.

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
