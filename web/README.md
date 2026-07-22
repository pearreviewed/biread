# biread web builder

An in-browser build of the reader: a reader drops in a French book, adds their
**own** Anthropic key, and gets the finished bilingual HTML — entirely
client-side, so no key or book text ever reaches a server of ours. The same
`biread` pipeline runs in the page via Pyodide (CPython on WASM); `worker.js`
runs it off the main thread so the page never freezes, and streams progress back.

It accepts the same formats the CLI does (`.txt · .epub · .pdf · .html · .docx`),
prices a run for free before spending, and lets the reader pick the model
(Haiku → Sonnet → Opus). Without a key, a reader can still bring both an original
and a published translation and read them side by side, free — *(that free path
is still to come.)*

## Build the deployable

    python web/build.py

That produces `web/dist/` — the wheel, the fonts, the page, and the worker.
Pyodide loads from a CDN, so `web/dist/` is a plain static site: serve it, or
drop it on any static host.

## Try it locally

    python web/build.py && python -m http.server -d web/dist
    # open http://localhost:8000/builder.html
