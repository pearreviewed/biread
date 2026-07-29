// The builder's engine, off the main thread. Boots Pyodide + biread, then
// answers two commands: "estimate" (pure Python, no API) and "build" (runs the
// pipeline on the reader's own key, streaming progress). The page never blocks.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

const WHEEL_URL = new URL("biread-0.1.0-py3-none-any.whl", self.location.href).href;
let pyodide;

// Read a file into chapters once and keep it: the keyed path prices the book
// (which reads it) and then builds it, and re-reading a PDF glyph by glyph the
// second time is the slowest thing the builder does. Reading also reports its
// pages, so a long PDF shows "page 12 of 147" instead of sitting silent.
const SETUP = [
  "from pathlib import Path",
  "from biread.extract import get_extractor",
  "from biread.cleanup import clean",
  "_BOOKS = {}",
  "def read_book(path, stage):",
  "    if path and path not in _BOOKS:",
  "        ext = get_extractor(Path(path))",
  "        raw = ext.extract(Path(path), on_page=lambda d, t: js_progress(stage, d, t))",
  "        _BOOKS[path] = clean(raw)[0]",
  "    return _BOOKS.get(path)",
].join("\n");

const ready = (async () => {
  pyodide = await loadPyodide();
  await pyodide.loadPackage("micropip");
  await pyodide.runPythonAsync("import micropip\nawait micropip.install('" + WHEEL_URL + "', deps=False)");
  try { pyodide.FS.mkdir("/in"); } catch (e) {}
  const langs = pyodide.runPython([
    "import json",
    "from biread.targets import TARGETS, DEFAULT_LANG",
    "json.dumps({'default': DEFAULT_LANG, 'items': sorted([[k, t.name] for k, t in TARGETS.items()], key=lambda x: x[1])})",
  ].join("\n"));
  pyodide.globals.set("js_progress", () => {});
  pyodide.runPython(SETUP);
  postMessage({ type: "ready", langs: JSON.parse(langs) });
})();

// Shared setup: turn the uploaded files into chapters and a Config.
const LOAD = [
  "from biread.config import Config, lookup_price",
  "from biread.cache import Cache",
  "from biread.targets import get_target",
  "orig_chapters = read_book(orig_path, 'read-orig')",
  "pub_chapters = read_book(pub_path, 'read-pub')",
  "target = get_target(lang_key)",
  // Price comes live from the provider (OpenRouter lists every model's rate), so
  // a model absent from the built-in table — Qwen 3 8B, say — still prices exactly.
  "price = (price_in, price_out) if price_in else lookup_price(MODEL)",
  "cfg = Config(provider=provider, model=MODEL, model_gloss=MODEL, api_key=(api_key or None), ollama_host='', base_url=(base_url or None), max_cost_usd=10**9, price_per_mtok=price)",
].join("\n");

const ESTIMATE = [
  "MODEL = model_id",
  LOAD,
  "from biread.translate import estimate as est_tr",
  "from biread.gloss import estimate as est_gl",
  "import json",
  "e = est_tr(orig_chapters, Cache(None), cfg, target.name)",
  "cost = e.cost or 0.0",
  "gloss_cost = None",
  "if want_gloss:",
  "    g = est_gl(orig_chapters, Cache(None), cfg.for_glossing(), target.name)",
  "    gloss_cost = g.cost or 0.0",
  "    cost += gloss_cost",
  "json.dumps({'paragraphs': e.total, 'pending': e.pending, 'translate_cost': e.cost, 'gloss_cost': gloss_cost, 'cost': cost, 'model': MODEL})",
].join("\n");

const BUILD = [
  "MODEL = model_id",
  LOAD,
  "from biread.build import build_reader",
  "if provider == 'anthropic':",
  "    from biread.llm.pyodide_client import PyodideAnthropicClient",
  "    client = PyodideAnthropicClient(MODEL, api_key)",
  "else:",
  "    from biread.llm.pyodide_openai_client import PyodideOpenAIClient",
  "    client = PyodideOpenAIClient(MODEL, api_key, base_url or 'https://api.openai.com/v1')",
  "res = build_reader(title=title, chapters=orig_chapters, client=client, cache=Cache(None), cfg=cfg, target=target, published_chapters=pub_chapters, gloss=bool(want_gloss), on_progress=lambda s, d, t: js_progress(s, d, t))",
  "res.html",
].join("\n");

self.onmessage = async (e) => {
  await ready;
  const m = e.data;
  try {
    const names = [m.origName, m.pubName].filter(Boolean).join(" ").toLowerCase();
    if (names.includes(".pdf")) {
      await pyodide.runPythonAsync("import micropip\nawait micropip.install('pypdf')");
    }
    const origPath = m.orig ? write("orig_" + m.origName, m.orig) : null;
    const pubPath = m.pub ? write("pub_" + m.pubName, m.pub) : null;
    pyodide.globals.set("orig_path", origPath);
    pyodide.globals.set("pub_path", pubPath);
    pyodide.globals.set("lang_key", m.lang);
    pyodide.globals.set("want_gloss", !!m.gloss);
    pyodide.globals.set("api_key", m.key || "");
    pyodide.globals.set("title", m.title || "book");
    pyodide.globals.set("model_id", m.model || "claude-sonnet-5");
    // Provider, its base URL, and the model's live price (input/output $ per Mtok)
    // all come from the page, which knows what the reader picked and what it costs.
    pyodide.globals.set("provider", m.provider || "anthropic");
    pyodide.globals.set("base_url", m.baseUrl || "");
    pyodide.globals.set("price_in", m.priceIn || 0);
    pyodide.globals.set("price_out", m.priceOut || 0);
    // Live from here on: reading a PDF reports its pages during pricing and the
    // free build alike, not only while translating.
    pyodide.globals.set("js_progress", (s, d, t) => postMessage({ type: "progress", stage: s, done: d, total: t }));

    if (m.type === "estimate") {
      postMessage({ type: "estimate", data: JSON.parse(await pyodide.runPythonAsync(ESTIMATE)) });
    } else if (m.type === "build") {
      postMessage({ type: "done", html: await pyodide.runPythonAsync(BUILD) });
    }
  } catch (err) {
    postMessage({ type: "error", error: cleanError(err) });
  }
};

function cleanError(err) {
  // Pyodide errors arrive as a full traceback; show only the final message.
  const lines = String(err).trim().split("\n");
  const last = lines[lines.length - 1].trim();
  const m = last.match(/(?:Error|Exception):\s*(.+)$/);
  return m ? m[1] : last;
}

function write(name, bytes) {
  // Idempotent, so pricing then building the same upload does not rewrite the
  // file and drop its cached reading. A genuinely new file for a name reused in
  // the session is rewritten, and its stale reading forgotten.
  const path = "/in/" + name;
  try {
    const old = pyodide.FS.readFile(path);
    if (old.length === bytes.length && old.every((b, i) => b === bytes[i])) return path;
  } catch (e) {}
  pyodide.FS.writeFile(path, bytes);
  pyodide.runPython("_BOOKS.pop(" + JSON.stringify(path) + ", None)");
  return path;
}
