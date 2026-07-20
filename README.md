# biread

Turn a plain-text French book into a single self-contained HTML file: an
open-book spread with the French on the left page and an English translation on
the right, paginated at runtime like a real book.

The output is one file. No server, no network, no build step — open it in a
browser, or email it to someone.

## Quick start

```sh
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then add your API key

python -m biread book.txt --dry-run          # what would this cost?
python -m biread book.txt -o output/
```

`--dry-run` needs no API key, so you can price a book before setting anything up.

## Options

| Flag | What it does |
| --- | --- |
| `-o, --output DIR` | Where to write the HTML (default `output/`) |
| `--published FILE` | Also show a published English translation you already own |
| `--title TEXT` | Title in the reader header (default: from the filename) |
| `--cache-dir DIR` | Where translation caches live (default `cache/`) |
| `--dry-run` | Report uncached work and an estimated cost, then stop |
| `--force` | Proceed with books above 2,000 paragraphs |
| `--rebuild-cache` | Discard a cache written by an incompatible version |

## Cost, caching, and interruptions

Translation is the only thing that costs money, and every paragraph is cached
by content hash the moment it comes back. So:

- Re-running a finished book costs nothing.
- Interrupting mid-run loses at most the batch in flight.
- `MAX_COST_USD` stops a run cleanly once the running estimate crosses it. Raise
  it and re-run to continue where you left off.

The cap can only be enforced for models with known pricing. For anything else,
set `PRICE_PER_MTOK` in `.env` — otherwise biread warns and runs uncapped.

`cache/` is the expensive, rebuildable asset. Back it up by copying the
directory; it is plain JSON.

## Reading a published translation alongside

```sh
python -m biread french.txt --published english.txt
```

Published translations do not preserve paragraph breaks — translators split a
paragraph of dialogue into several, or merge two into one — and a published
edition carries matter the source has none of: a title page, a transcriber's
note, footnotes set as their own paragraphs. Pairing by position gets this
badly wrong: on the bundled Micromégas the published edition has 34 paragraphs
of front matter before the text even starts.

So biread aligns by content instead, using the generated translation as a
pivot. That translation is tied to each French paragraph exactly, by
construction, which turns the problem into matching English against English.
Each published paragraph is matched to the one it most resembles, in reading
order; anything resembling nothing — front matter, footnotes — is left out, and
a French paragraph with no counterpart is left blank rather than filled with a
guess. The toggle in the header cross-fades between the two English columns.

This needs the translation to exist first, so alignment runs after it. Without
one, biread falls back to distributing proportionally within each chapter and
says so.

## How pages are laid out

Pagination happens in the browser, against the real page box, one chapter at a
time. Paragraphs fill a page until the next one won't fit; a paragraph too tall
for a whole page continues onto the next, with both columns broken at the same
fraction through it so French and English meet again where it ends. A resumed
paragraph starts flush instead of indented, as in a printed book. Pages never
scroll.

## In the reader

Click either half of the book, or `←` / `→` / `Space` / swipe, to turn a page;
hold Shift to jump ten. `A−` / `A+` resize the text and repaginate around where
you are. **Blur translation** hides the English until you hover a paragraph.
The star bookmarks a spread, the ribbon removes it, and your place is restored
next time — all stored as positions in the book, so they survive resizing the
window or changing the font size. Everything lives in `localStorage` under
`biread:<book>:`.

## Adding a format

`.txt` today. An extractor's only job is file → raw string: subclass
`Extractor` in `biread/extract/`, declare its `suffixes`, and register it in
`EXTRACTORS`. Stripping boilerplate, rejoining wrapped lines, and finding
chapters all happen downstream in `cleanup.py`, so nothing else changes.

Non-UTF-8 sources are decoded as cp1252 if UTF-8 fails, which covers most
legacy French texts.

## Layout

```
biread/
  cli.py          argument parsing and everything the user sees printed
  extract/        source file -> raw text
  cleanup.py      raw text -> chapters of clean paragraphs
  translate.py    paragraphs -> English, batched and cached
  align.py        a published translation -> aligned to the French
  render/         book -> one HTML file (templates/ holds the real reader)
  llm/            one thin client per provider
  cache.py        content-hash JSON cache
  config.py       environment, models, pricing
```

The reader itself is `biread/render/templates/reader.{html,css,js}` — plain
files, edited as plain files. `render/__init__.py` only inlines the fonts and
paper texture and substitutes the book data.

## Tests

```sh
pip install -e ".[dev]"
pytest
```

No test touches the network. The model is a fake that echoes structured
replies, including malformed and truncated ones, and the three provider
clients are tested against stubbed SDK responses.

The reader itself is driven in a real browser, because its bugs live in layout
and timing — pagination measured against a box that had not been laid out yet,
a drag target destroyed mid-gesture — and none of those are reachable without a
rendering engine. Those tests skip unless the browser extra is installed:

```sh
pip install -e ".[browser]" && playwright install chromium
pytest tests/test_reader_js.py
```
