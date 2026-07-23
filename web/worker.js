// The builder's engine, off the main thread. Boots Pyodide + biread, then
// answers two commands: "estimate" (pure Python, no API) and "build" (runs the
// pipeline on the reader's own key, streaming progress). The page never blocks.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

const WHEEL_URL = new URL("biread-0.1.0-py3-none-any.whl", self.location.href).href;
let pyodide;

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
  postMessage({ type: "ready", langs: JSON.parse(langs) });
})();

// Shared setup: turn the uploaded files into chapters and a Config.
const LOAD = [
  "from pathlib import Path",
  "from biread.extract import get_extractor",
  "from biread.cleanup import clean",
  "from biread.config import Config, lookup_price",
  "from biread.cache import Cache",
  "from biread.targets import get_target",
  "orig_chapters, _ = clean(get_extractor(Path(orig_path)).extract(Path(orig_path)))",
  "pub_chapters = None",
  "if pub_path:",
  "    pub_chapters, _ = clean(get_extractor(Path(pub_path)).extract(Path(pub_path)))",
  "target = get_target(lang_key)",
  "cfg = Config(provider='anthropic', model=MODEL, model_gloss=MODEL, api_key=(api_key or None), ollama_host='', base_url=None, max_cost_usd=10**9, price_per_mtok=lookup_price(MODEL))",
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
  "from biread.llm.pyodide_client import PyodideAnthropicClient",
  "client = PyodideAnthropicClient(MODEL, api_key)",
  "res = build_reader(title=title, chapters=orig_chapters, client=client, cache=Cache(None), cfg=cfg, target=target, published_chapters=pub_chapters, gloss=bool(want_gloss), on_progress=lambda s, d, t: js_progress(s, d, t))",
  "res.html",
].join("\n");

// Free path: no key, no AI — set a brought translation beside the French by position.
const LOAD_FREE = [
  "from pathlib import Path",
  "from biread.extract import get_extractor",
  "from biread.cleanup import clean",
  "from biread.targets import get_target",
  "orig_chapters, _ = clean(get_extractor(Path(orig_path)).extract(Path(orig_path)))",
  "pub_chapters, _ = clean(get_extractor(Path(pub_path)).extract(Path(pub_path)))",
  "target = get_target(lang_key)",
].join("\n");

const BUILD_FREE = [
  LOAD_FREE,
  "from biread.build import build_positional",
  "html, _ = build_positional(title=title, chapters=orig_chapters, published_chapters=pub_chapters, target=target)",
  "html",
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

    if (m.type === "estimate") {
      postMessage({ type: "estimate", data: JSON.parse(await pyodide.runPythonAsync(ESTIMATE)) });
    } else if (m.type === "build") {
      pyodide.globals.set("js_progress", (s, d, t) => postMessage({ type: "progress", stage: s, done: d, total: t }));
      postMessage({ type: "done", html: await pyodide.runPythonAsync(BUILD) });
    } else if (m.type === "build-free") {
      postMessage({ type: "done", html: await pyodide.runPythonAsync(BUILD_FREE) });
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
  pyodide.FS.writeFile("/in/" + name, bytes);
  return "/in/" + name;
}
