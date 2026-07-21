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
| `--gloss` | Annotate the French for hover translation (costs extra; see `--dry-run`) |
| `--epub` | Also write a reflowable EPUB, glosses as tap-to-reveal notes |
| `--pdf` | Also write a print PDF, French and English side by side (needs `[browser]`) |
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
window or changing the font size.

## Saving your place

Progress saves itself. Every page turn records where you are; the star records a
bookmark. Reopen the book and it offers to resume. There is no account to make
and no button to press — nothing is uploaded, because there is nowhere to upload
it to.

It is kept in the browser's `localStorage`, under keys prefixed `biread:<book>:`.
Two consequences follow from that, both by design:

- **It is per-browser, per-device.** Your phone and your laptop keep separate
  places; two people sharing one browser share one place. That is the price of
  having no login, and for a book you hand around it is usually the right one.
- **Clearing the browser's site data resets it.** Private/incognito windows
  start blank and forget on close. Nothing else touches it.

Each book is keyed by its own slug, so several biread books on one site do not
collide.

Because saving is entirely client-side, **hosting is just static files** —
GitHub Pages, an S3 bucket, or a file on disk all behave the same. Anyone who
opens the page gets their own autosaving copy, no backend and no sign-in.

### Carrying your place to another device

The address bar always points at your place (`…/book.html#p42b7.51`), updated
silently as you read and as you bookmark. That link *is* your reading state —
the page (`p42`) and every bookmark (`b7.51`) — so it travels where local
storage cannot: copy it (the link button by the page counter does this and
flashes *Link copied*) and open it on a phone to arrive at the same page with
the same bookmarks. Opening a link goes straight there, ahead of any saved
position; the bookmarks it carries are merged into whatever the device already
had, so nothing is lost either way. The one requirement is that the book be
hosted at a shared URL rather than emailed as a local file, since a `file://`
path is not the same on two machines.

What is left, and genuinely needs a server, is silent *sync* — two devices
staying current without anyone copying a link. That is a different project from
this one.

## Exporting to EPUB and PDF

The reader is one interactive HTML file; `--epub` and `--pdf` write static
copies for reading elsewhere. Neither calls the API — they transform text that
is already generated and cached — but each keeps only what its medium can hold.

- **`--epub`** is a reflowable e-book for Kindle, Apple Books, or a phone.
  E-readers paginate for themselves, so there is no two-page spread: the French
  and English interleave, paragraph by paragraph. A glossed word becomes an
  EPUB 3 footnote — Apple Books reveals it on a tap, others show a note at the
  chapter's end. Built with the standard library, no extra dependency.
- **`--pdf`** is for print: the French and English side by side in two columns,
  aligned paragraph by paragraph, matching the reader's type. Glosses are left
  out — footnotes for every hover would bury the page. It is printed by headless
  Chromium, so it needs the `[browser]` extra:
  `pip install -e ".[browser]" && playwright install chromium`.

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

## License

[MIT](LICENSE) — use it, change it, ship it; just keep the copyright notice.
