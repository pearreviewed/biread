# Contributing to biread

Thanks for wanting to help. biread turns a plain-text French book into one
self-contained bilingual HTML reader; the [README](README.md) explains what it
does and [CLAUDE.md](CLAUDE.md) records the decisions behind it — read that
before proposing a change to settled behaviour, so a reversal isn't re-argued.

## Setup

```sh
git clone <your fork>
cd bilingual-reader
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

That's enough for everything except the browser tests and the EPUB and PDF
export, which drive a real headless Chromium:

```sh
pip install -e ".[browser]" && playwright install chromium
```

## Tests

```sh
pytest
```

The suite **needs no network and no API key** — the model is faked and the
fixtures are canned — so you can run all of it for free, as often as you like.
The ~54 browser tests (and the EPUB/PDF export render tests) skip themselves
unless the `[browser]` extra is installed.

CI runs the Python tests on every push and pull request, and the browser tests
alongside; a change has to be green to merge. If you fix a bug, add the test
that would have caught it — the reader's expensive bugs have all been layout and
timing, and none are reachable without a rendering engine, so drive the real
thing rather than trusting a mock.

## Style

The codebase has a particular grain; match it rather than your own defaults.

- **Comments explain _why_, not _what_.** If the code says what it does, don't
  restate it. Spend the comment on the thing that isn't on the screen: why this
  and not the obvious alternative, what breaks if you change it, the bug it
  already cost.
- **Less is more.** No defensive bloat, no ceremony, no scaffolding for a
  generality no one asked for. Elegant and small beats thorough and noisy.
- **Match the surrounding code** — its naming, its structure, its comment
  density. A change should read like the file it lands in.
- The reader is plain `reader.{html,css,js}` in `biread/render/templates/`.
  Edit them as plain files; `render/` only inlines the assets and the book data.

## Money — the one thing to be careful with

Translation and `--gloss` call a **paid** API. The tests never do, but a real
build does. If you touch the pipeline:

- Price a change with `--dry-run` first — it needs no key and calls nothing.
- Never run two builds against the same cache at once; they can clobber each
  other's writes.
- Never commit your `.env`. It is gitignored; keep it that way.

## Submitting a change

1. Branch off `main`.
2. Keep commits focused, and write the message about **why** the change is
   needed, not just what it does.
3. Make sure `pytest` is green, and add or update tests for what you changed.
4. Open a pull request. CI will run the suite; keep it passing.

Small, sharp changes are easier to accept than large ones. If you're planning
something big, open an issue first so we can talk it through before you build.
