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
it translates with the chat model.

## Build the deployable

    python web/build.py

That produces `web/dist/` — the wheel, the fonts, the page, and the worker.
Pyodide loads from a CDN, so `web/dist/` is a plain static site: serve it, or
drop it on any static host.

## Try it locally

    python web/build.py && python -m http.server -d web/dist
    # open http://localhost:8000/builder.html
