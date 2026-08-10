# biread web builder

An in-browser build of the reader: a reader drops in a French book, brings their
**own** model, and gets the finished bilingual HTML — entirely client-side, so no
key or book text ever reaches a server of ours. The same `biread` pipeline runs
in the page via Pyodide (CPython on WASM); `worker.js` runs it off the main
thread so the page never freezes, and streams progress back. It accepts the same
formats the CLI does (`.txt · .epub · .pdf · .html · .docx`).

**Everything goes through a model — the translation and the alignment both.** The
old shortcut, which matched two editions on the names, numbers and sentence
lengths they happened to share, is gone: two translations of one book share their
*meaning*, not their words, so a surface-token matcher has a ceiling that tuning
does not raise, and it failed quietly rather than loudly.

Which model is the reader's choice, and the page offers two ways to bring one:

- **Local · Ollama — free.** The models run on the reader's own machine: a chat
  model (GPT-OSS 20B by default) to translate, BGE-M3 to align. No key, nothing
  sent anywhere, no price to show. One-time setup — starting Ollama with this
  page's origin allowed, then pulling the two models — is printed on the page.
  It wants a capable computer; 20B expects roughly 16 GB of RAM.
- **OpenRouter — paid, priced first.** Three tiers (**Cheapest / Balanced /
  Finest**) each name a real model with its live per-Mtok rate, read from
  OpenRouter's models API, and any other model id can be pasted in instead. The
  page then prices that reader's whole book exactly, for the model they picked,
  before the first request.

Free is therefore back, but on a different footing than before: free now means
*the model runs on your machine*, not *we matched your two books without one*.

Bring a published edition you own and the builder aligns it by meaning through
the embedding path — no translation of its own needed. Bring only the French and
it translates with the chat model. Bring nothing at all and there is a third
route: **pick from the shelf**, where both editions are fetched from Wikisource
and Standard Ebooks by the reader's own browser. biread stores two page names per
book and never a word of text, which is what keeps it a tool rather than a host.

## Four things the page does that are easy to miss

- **The price comes after a sample page, not before.** `sample_translate` runs
  the chosen model over three real paragraphs of the reader's own book and
  renders them in a miniature of the reader's spread, so the estimate is a price
  on prose already seen rather than a promise about quality.
- **A build survives the tab closing.** Every paragraph paid for is written to
  IndexedDB as it lands, keyed by a hash of the book's own text and filed per
  language. Coming back, the reader picks the same file and the engine is handed
  what is already held *before* the estimate runs, so the price screen quotes
  only what is left and says so.
- **Glossing runs six requests at a time**, in `gloss-pool.js`. The judgement
  stays in `gloss.py` — it hands over the batches it means to send and takes back
  the replies — while the transport moved out, because that pass is nothing but
  network. A local Ollama gets one hand instead of six, since a second request
  there only queues on the same card.
- **A book need not be fully glossed to be read.** The build makes the opening —
  measured in characters of the original rather than a count of paragraphs, since
  a book set in short dialogue lines and one set in long ones share nothing but
  the number — and the finished book carries the protocol so the rest is made on
  the reader's own key, one request at a time, as they read.
- **A book you built has somewhere to be found.** Every build also goes into the
  browser's own storage and stands on a row at the top of the front door, so the
  way back to it is not remembering what the file was called. That row is
  emphatically **not** the shelf: the shelf below is published and vouched for,
  and this is one person's own files. It says so in its own words, nothing about
  it reaches a server, and it is one browser only — clearing site data takes the
  row with it, which is why the file itself is still offered on the card.

Two things the page will tell a reader before they pay: that their file is a
**photograph of a book** rather than a typeset one, since biread leaves OCR
misreadings exactly as the file has them; and that a file which arrived with no
paragraph breaks was cut to its counterpart's shape.

## Build the deployable

    python web/build.py

That produces `web/dist/` — the wheel, the fonts, the page, and the worker.
Pyodide loads from a CDN, so `web/dist/` is a plain static site: serve it, or
drop it on any static host.

## Try it locally

    python web/build.py && python -m http.server -d web/dist
    # open http://localhost:8000/builder.html
