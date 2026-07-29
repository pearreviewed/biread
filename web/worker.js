// The builder's engine, off the main thread. Boots Pyodide + biread, then
// answers the page's commands — inspect a file, buy one sample page, price the
// run, build the book — streaming progress and finished prose as they arrive.
// The page never blocks.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

const WHEEL_URL = new URL("biread-0.1.0-py3-none-any.whl", self.location.href).href;
let pyodide;

// Read a file into chapters once and keep it: a book is inspected, sampled,
// priced and built in one sitting, and re-reading a PDF glyph by glyph each time
// is the slowest thing the builder does. Reading also reports its pages, so a
// long PDF shows "page 12 of 147" instead of sitting silent.
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

const READ = [
  "orig_chapters = read_book(orig_path, 'read-orig')",
  "pub_chapters = read_book(pub_path, 'read-pub')",
].join("\n");

// Shared setup: turn the uploaded files into chapters and a Config.
const LOAD = [
  "from biread.config import Config, lookup_price",
  "from biread.cache import Cache",
  "from biread.targets import get_target",
  READ,
  "target = get_target(lang_key)",
  // Price comes live from the provider (OpenRouter lists every model's rate), so
  // a model absent from the built-in table — Qwen 3 8B, say — still prices exactly.
  "price = (price_in, price_out) if price_in else lookup_price(MODEL)",
  "cfg = Config(provider=provider, model=MODEL, model_gloss=MODEL, api_key=(api_key or None), ollama_host='', base_url=(base_url or None), max_cost_usd=10**9, price_per_mtok=price)",
].join("\n");

const CHAT_CLIENT = [
  "if provider == 'anthropic':",
  "    from biread.llm.pyodide_client import PyodideAnthropicClient",
  "    client = PyodideAnthropicClient(MODEL, api_key)",
  "else:",
  "    from biread.llm.pyodide_openai_client import PyodideOpenAIClient",
  "    client = PyodideOpenAIClient(MODEL, api_key, base_url or 'https://api.openai.com/v1')",
].join("\n");

const EMBEDDER = [
  "from biread.llm.pyodide_embed import PyodideEmbedder",
  "embedder = PyodideEmbedder(embed_model, api_key, base_url or 'https://openrouter.ai/api/v1')",
].join("\n");

// What each file says about itself. Reading it here is not wasted: the sample,
// the estimate and the build all reuse the chapters this warms.
const INSPECT = [
  "import json",
  "from biread.meta import describe",
  READ,
  "def _info(path, chapters):",
  "    if not path:",
  "        return None",
  "    i = describe(Path(path), chapters)",
  // Characters, so the page can price an embedding run without a second read.
  "    return {'title': i.title, 'author': i.author, 'language': i.language, 'pages': i.pages, 'paragraphs': i.paragraphs, 'chars': sum(len(p) for c in chapters for p in c.paragraphs)}",
  "json.dumps({'orig': _info(orig_path, orig_chapters), 'pub': _info(pub_path, pub_chapters)})",
].join("\n");

const indent = (code) => code.split("\n").map((line) => "    " + line).join("\n");

// One page, done for real, so the reader sees the prose before paying for the
// book. Translated by the chosen model, or matched against the edition brought.
const SAMPLE = [
  "MODEL = model_id",
  LOAD,
  "import json",
  "from biread.sample import sample_translate, sample_align",
  "if pub_path and route == 'align':",
  indent(EMBEDDER),
  "    s = sample_align(orig_chapters, pub_chapters, embedder.embed, sample_index)",
  "else:",
  indent(CHAT_CLIENT),
  "    s = sample_translate(orig_chapters, client, cfg, target.name, sample_index)",
  "json.dumps({'index': s.index, 'total': s.total, 'source': s.source, 'target': s.target, 'cost': s.cost})",
].join("\n");

// The aligned route translates nothing, so only its glosses are priced here; its
// embedding run is counted on the page, which knows the model's rate.
const ESTIMATE = [
  "MODEL = model_id",
  LOAD,
  "from biread.translate import estimate as est_tr",
  "from biread.gloss import estimate as est_gl",
  "import json",
  "out = {'model': MODEL, 'translate_cost': None, 'gloss_cost': None}",
  "if route == 'align':",
  "    out['paragraphs'] = sum(len(c.paragraphs) for c in orig_chapters)",
  "else:",
  "    e = est_tr(orig_chapters, Cache(None), cfg, target.name)",
  "    out.update(paragraphs=e.total, pending=e.pending, translate_cost=e.cost)",
  "if want_gloss:",
  "    g = est_gl(orig_chapters, Cache(None), cfg.for_glossing(), target.name)",
  "    out['gloss_cost'] = g.cost or 0.0",
  "out['cost'] = (out['translate_cost'] or 0.0) + (out['gloss_cost'] or 0.0)",
  "json.dumps(out)",
].join("\n");

const BUILD = [
  "MODEL = model_id",
  LOAD,
  "import json",
  "from biread.build import build_reader",
  CHAT_CLIENT,
  "res = build_reader(title=title, chapters=orig_chapters, client=client, cache=Cache(None), cfg=cfg, target=target, published_chapters=pub_chapters, gloss=bool(want_gloss), on_progress=lambda s, d, t: js_progress(s, d, t), on_text=lambda pairs: js_text(json.dumps(pairs)))",
  "spent = (res.translation.cost or 0.0) + ((res.gloss.cost or 0.0) if res.gloss else 0.0)",
  "json.dumps({'html': res.html, 'spent': spent})",
].join("\n");

// Align-only: no translation. Match a brought published edition to the French by
// meaning, with an embedding model — BGE-M3 on a local Ollama (free) or a cloud
// model (pennies). The published English becomes the single reading column.
const ALIGN = [
  "MODEL = model_id",
  LOAD,
  "import json",
  "from biread.build import build_aligned",
  EMBEDDER,
  // Glossing is chat-model work the embedding key usually also reaches, so the
  // hover survives the route that translates nothing.
  "gloss_client = None",
  "if want_gloss:",
  indent(CHAT_CLIENT),
  "    gloss_client = client",
  // The left page of the progress spread turns through the real book, so what it
  // shows at "paragraph 812 of 3,684" is the paragraph actually being matched.
  "js_text(json.dumps([[p, ''] for c in orig_chapters for p in c.paragraphs][:400]))",
  "res = build_aligned(title=title, chapters=orig_chapters, published_chapters=pub_chapters, embed=embedder.embed, target=target, gloss=bool(want_gloss), gloss_client=gloss_client, gloss_cfg=cfg.for_glossing(), on_progress=lambda s, d, t: js_progress(s, d, t))",
  "json.dumps({'html': res.html, 'spent': (res.gloss.cost or 0.0) if res.gloss else None})",
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
    pyodide.globals.set("lang_key", m.lang || "en");
    pyodide.globals.set("want_gloss", !!m.gloss);
    pyodide.globals.set("api_key", m.key || "");
    pyodide.globals.set("title", m.title || "book");
    pyodide.globals.set("model_id", m.model || "claude-sonnet-5");
    pyodide.globals.set("route", m.route || "translate");
    pyodide.globals.set("sample_index", m.sampleIndex || 0);
    // Provider, its base URL, and the model's live price (input/output $ per Mtok)
    // all come from the page, which knows what the reader picked and what it costs.
    pyodide.globals.set("provider", m.provider || "anthropic");
    pyodide.globals.set("base_url", m.baseUrl || "");
    pyodide.globals.set("price_in", m.priceIn || 0);
    pyodide.globals.set("price_out", m.priceOut || 0);
    pyodide.globals.set("embed_model", m.embedModel || "bge-m3");
    // Live from here on: reading a PDF reports its pages during pricing and the
    // free build alike, not only while translating.
    pyodide.globals.set("js_progress", (s, d, t) => postMessage({ type: "progress", stage: s, done: d, total: t }));
    // Finished prose, batch by batch, so the progress spread fills with the book
    // being made rather than a placeholder.
    pyodide.globals.set("js_text", (pairs) => postMessage({ type: "text", pairs: JSON.parse(pairs) }));

    if (m.type === "inspect") {
      postMessage({ type: "inspected", data: JSON.parse(await pyodide.runPythonAsync(INSPECT)) });
    } else if (m.type === "sample") {
      postMessage({ type: "sample", data: JSON.parse(await pyodide.runPythonAsync(SAMPLE)) });
    } else if (m.type === "estimate") {
      postMessage({ type: "estimate", data: JSON.parse(await pyodide.runPythonAsync(ESTIMATE)) });
    } else if (m.type === "build") {
      postMessage({ type: "done", ...JSON.parse(await pyodide.runPythonAsync(BUILD)) });
    } else if (m.type === "align") {
      postMessage({ type: "done", ...JSON.parse(await pyodide.runPythonAsync(ALIGN)) });
    }
  } catch (err) {
    postMessage({ type: "error", error: cleanError(err), during: m.type });
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
  // Idempotent, so inspecting then sampling then building the same upload does
  // not rewrite the file and drop its cached reading. A genuinely new file for a
  // name reused in the session is rewritten, and its stale reading forgotten.
  const path = "/in/" + name;
  try {
    const old = pyodide.FS.readFile(path);
    if (old.length === bytes.length && old.every((b, i) => b === bytes[i])) return path;
  } catch (e) {}
  pyodide.FS.writeFile(path, bytes);
  pyodide.runPython("_BOOKS.pop(" + JSON.stringify(path) + ", None)");
  return path;
}
