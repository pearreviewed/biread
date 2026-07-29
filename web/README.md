# biread web builder

An in-browser build of the reader: a reader drops in a French book, adds their
**own** OpenRouter key, and gets the finished bilingual HTML — entirely
client-side, so no key or book text ever reaches a server of ours. The same
`biread` pipeline runs in the page via Pyodide (CPython on WASM); `worker.js`
runs it off the main thread so the page never freezes, and streams progress back.

It accepts the same formats the CLI does (`.txt · .epub · .pdf · .html · .docx`).
A key is required. The old no-key path — two editions matched by the names,
numbers and sentence lengths they happen to share — is gone: two translations of
one book share their *meaning*, not their words, so a surface-token matcher has
a ceiling, and it failed quietly rather than loudly. Both the translation and
the alignment now go through a model.

The model is the reader's choice, priced before anything is spent. Three tiers —
**Cheapest / Balanced / Finest** — each name a real model with its live per-Mtok
rate, read from OpenRouter's models API, and any other model id can be pasted in
instead; the page then prices that reader's whole book exactly, for the model
they picked, before the first request. The tool is free; the model is theirs.

## Build the deployable

    python web/build.py

That produces `web/dist/` — the wheel, the fonts, the page, and the worker.
Pyodide loads from a CDN, so `web/dist/` is a plain static site: serve it, or
drop it on any static host.

## Try it locally

    python web/build.py && python -m http.server -d web/dist
    # open http://localhost:8000/builder.html
