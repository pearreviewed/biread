// The builder's engine, off the main thread. Boots Pyodide + biread, then
// answers the page's commands — inspect a file, buy one sample page, price the
// run, build the book — streaming progress and finished prose as they arrive.
// The page never blocks.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");
// The gloss pass's transport: `ask` and `glossInParallel`, which do the one part
// of a build that has to happen out here rather than in the engine.
importScripts(new URL("gloss-pool.js", self.location.href).href);

// The name below is a placeholder: `web/build.py` stamps the wheel's own content
// hash into it when the bundle is assembled, and rewrites this line to match. It
// has to, because the wheel is the one file worth caching for a year and its
// version changes once a release rather than once a build — so a returning
// reader was served today's worker against the engine their browser cached on
// its first ever visit, and the page called a `biread.build` function that
// engine had never heard of.
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
  "from biread.meta import looks_scanned",
  "_BOOKS = {}",
  // Weighed here because this is the only place the raw text exists: a scan
  // stores an image of every page beside the characters read off it, so the file
  // is enormous against its own text. Kept as one boolean rather than the text,
  // which the tab is already holding once as chapters.
  "_SCANNED = {}",
  "def read_book(path, stage):",
  "    if path and path not in _BOOKS:",
  "        ext = get_extractor(Path(path))",
  "        raw = ext.extract(Path(path), on_page=lambda d, t: js_progress(stage, d, t))",
  "        _SCANNED[path] = looks_scanned(Path(path), raw)",
  "        _BOOKS[path] = clean(raw, from_pdf=Path(path).suffix.lower() == '.pdf')[0]",
  "    return _BOOKS.get(path)",
  // Judged with both files in hand, never one at a time: where one lost its
  // paragraph breaks and the other kept them, the other's shape is what puts
  // them back, and a file-by-file refusal would never find that out. Imported
  // here rather than at startup — the build engine pulls in the templates and
  // every provider behind it, and nothing is read until a reader picks a file.
  "def judge(orig, pub, orig_name, pub_name):",
  "    from biread.build import check_usable, recut",
  "    orig, pub, _ = recut(orig, pub) if orig else (orig, pub, '')",
  "    if orig: check_usable(orig, 'The book', orig_name or None)",
  "    if pub: check_usable(pub, 'The published translation', pub_name or None)",
  "    return orig, pub",
  // A book off the shelf arrives over the network instead of off the disk. The
  // reader's own browser fetches it — nothing here is ours to hold — and the two
  // editions are kept for the same sitting the uploads are.
  "from pyodide.http import open_url",
  "_SHELF = {}",
  "def ws_fetch(url):",
  "    return open_url(url).read()",
  // What a build has already paid for, by content hash, kept for as long as the
  // page can keep it. Nothing here is a copy of a book: the keys are hashes and
  // the values are the translations and glosses this reader bought. `on_write`
  // hands each one to the page as it lands, which is what survives the tab.
  "import json",
  // A book's own name for itself: the hash of the text it is made of. Two
  // uploads of the same edition under different filenames are the same book and
  // share the work already paid for; a different edition is a different book.
  "def book_key(chapters):",
  "    from biread.translate import hash_text",
  "    return hash_text('\\n'.join(p for c in (chapters or []) for p in c.paragraphs))",
  "_CACHES = {}",
  "def cache_slot(key):",
  "    return _CACHES.setdefault(key, {})",
  "def restore(key, payload):",
  "    cache_slot(key).update(json.loads(payload))",
  "    return len(_CACHES[key])",
  // The book between its two halves: made, not yet glossed, not yet set in type.
  "_JOB = {}",
  "def gloss_task():",
  "    from biread.gloss import MAX_TOKENS, opening, plan_gloss",
  // How much of the hover the build itself makes. The opening is sized from the
  // book rather than sent as a number, because only this side has the
  // paragraphs: the page knows a total and an average, and an average buys a
  // different amount of reading in every book.
  "    limit = opening(_JOB['draft'].chapters) if gloss_opening else None",
  "    plan = plan_gloss(_JOB['draft'].chapters, _JOB['cache'], _JOB['target'].name, limit)",
  "    _JOB['plan'] = plan",
  "    js_progress('gloss', plan.run.done, plan.run.total)",
  "    return json.dumps({'system': plan.system(0), 'retry': plan.system(1),",
  "                       'maxTokens': MAX_TOKENS,",
  "                       'batches': [{'n': n, 'prompt': plan.prompt(n)}",
  "                                   for n in range(len(plan.groups))]})",
  "def gloss_take(n, text):",
  "    from biread.gloss import absorb",
  "    return absorb(_JOB['plan'], int(n), text, _JOB['cache'],",
  "                  lambda d, t: js_progress('gloss', d, t))",
  "def gloss_off(n):",
  "    from biread.gloss import written_off",
  "    written_off(_JOB['plan'], int(n))",
  // A batch nothing could be anchored in is retried here one paragraph at a
  // time, on the blocking client — there are few of them, and they are the calls
  // that need the model's whole attention rather than the network's.
  "def gloss_end(tokens_in, tokens_out):",
  "    from biread.gloss import rescue_failures",
  "    plan, client, cfg = _JOB['plan'], _JOB['client'], _JOB['cfg']",
  "    was = (client.input_tokens, client.output_tokens)",
  "    rescue_failures(plan, client, _JOB['cache'], lambda d, t: js_progress('gloss', d, t))",
  "    plan.run.cost = cfg.estimate_cost(int(tokens_in) + client.input_tokens - was[0],",
  "                                      int(tokens_out) + client.output_tokens - was[1])",
  "    _JOB['run'] = plan.run",
  "def build_end():",
  "    from biread.build import finish",
  // The protocol travels with every book, so one whose opening was glossed — or
  // which was built with no hover at all — is finished by whoever reads it, on
  // their own key. It costs a few kilobytes and saves the hours a full gloss
  // pass would have taken before page one.
  //
  // Written whether or not this build made a chat client, which is the whole of
  // it: the align route asks for a model only once the hover is wanted, so a
  // book aligned with the box unticked came out sealed — no hover, and no way
  // for its reader to add one ever. A model was still chosen on the page.
  // Local builds name Ollama, since a model on the builder's own machine is not
  // one the book can send a reader to.
  "    offer = {'provider': ('ollama' if local_engine else provider), 'model': MODEL, 'lang': _JOB['target'].name}",
  "    res = finish(_JOB['draft'], _JOB.get('run'), offer)",
  "    tr = res.translation.cost if res.translation else None",
  "    gl = res.gloss.cost if res.gloss else None",
  "    spent = None if tr is None and gl is None else (tr or 0.0) + (gl or 0.0)",
  "    _JOB.clear()",
  "    return json.dumps({'html': res.html, 'spent': spent})",
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
  const shelf = pyodide.runPython([
    "import json",
    "from biread.shelf import catalogue",
    "json.dumps(catalogue())",
  ].join("\n"));
  pyodide.globals.set("js_progress", () => {});
  pyodide.globals.set("shelf_key", null);
  pyodide.runPython(SETUP);
  postMessage({ type: "ready", langs: JSON.parse(langs), shelf: JSON.parse(shelf) });
})();

const READ = [
  "if shelf_key:",
  "    orig_chapters, pub_chapters = _SHELF[shelf_key]",
  "else:",
  "    orig_chapters = read_book(orig_path, 'read-orig')",
  "    pub_chapters = read_book(pub_path, 'read-pub')",
  "    orig_chapters, pub_chapters = judge(orig_chapters, pub_chapters, orig_name, pub_name)",
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
  // Everything this reader has already paid for on this book, and a hook that
  // hands each new entry to the page to be kept. A cache key is a content hash,
  // so an entry made a fortnight ago on the same paragraph is the same entry.
  "cache = Cache(None, cache_slot(work_key), on_write=lambda e: js_cached(json.dumps(e)))",
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
  "    i = describe(Path(path), chapters, _SCANNED.get(path))",
  // Characters, so the page can price an embedding run without a second read.
  "    return {'title': i.title, 'author': i.author, 'language': i.language, 'pages': i.pages, 'paragraphs': i.paragraphs, 'scanned': i.scanned, 'chars': sum(len(p) for c in chapters for p in c.paragraphs)}",
  "json.dumps({'orig': _info(orig_path, orig_chapters), 'pub': _info(pub_path, pub_chapters), 'key': book_key(orig_chapters)})",
].join("\n");

const indent = (code) => code.split("\n").map((line) => "    " + line).join("\n");

// A book off the shelf: two page names in, two editions out. The fetch is the
// reader's browser talking to Wikisource — biread holds the page names and never
// the text, which is the whole reason the shelf can exist at all.
const SHELF = [
  "import json",
  "from biread import shelf as shelf_mod",
  "book = shelf_mod.by_slug(shelf_slug) if shelf_slug else None",
  "if book:",
  "    orig_chapters, pub_chapters, info = shelf_mod.load_pair(book, translation_index, ws_fetch, js_progress)",
  "else:",
  "    f = json.loads(found_json)",
  // A found book's English half may be the wiki's or the second library's. Which
  // one is the only thing that differs, and load_pages already knows both.
  "    where = shelf_mod.Translation(f['otherPage'], f.get('translator'),",
  "                                  source=f.get('source') or 'wikisource')",
  "    orig_chapters, pub_chapters, info = shelf_mod.load_pages(",
  "        f['lang'], f['page'], f['other'], f['otherPage'], ws_fetch, js_progress,",
  "        (f.get('title'), f.get('author'), f.get('translator')), where)",
  "_SHELF[shelf_key] = (orig_chapters, pub_chapters)",
  "info['key'] = book_key(orig_chapters)",
  "json.dumps(info)",
].join("\n");

// Looking beyond the shelf. The search and the two editions' whereabouts are
// separate questions, and the second is answered book by book so the page can
// fill each card in as its answer arrives rather than sitting on all of them.
//
// Every hit with a counterpart is probed — no quota. A card is drawn the moment
// the search lands, so a hit left unprobed reads "Looking for both editions…"
// for as long as the reader is willing to wait: the old cap of three did not
// show less, it showed a lie. Four probes are the reader's own browser asking
// the wiki, and they cost nothing but a moment.
const LOOK_PAGE = 4;
const LOOKUP = [
  "import json",
  "from biread import wikisource as ws, shelf as shelf_mod, standardebooks as se",
  `found = ws.search(query, look_lang, ${LOOK_PAGE}, look_offset, ws_fetch)`,
  "pairs = ws.counterparts([h.title for h in found.hits], look_lang, look_other, ws_fetch)",
  // The count travels with the results, not with the run's return value: the
  // probes come between them, and what was left behind should not wait on them.
  "js_hits(json.dumps({'more': found.more, 'hits': [{'title': h.title, 'snippet': h.snippet, 'counterpart': pairs.get(h.title)} for h in found.hits]}))",
  "probed = 0",
  // One search of the second library per author, not per book: a page of results
  // is often three works by the same writer, and their shelf there is one page.
  "by_author = {}",
  "for h in found.hits:",
  "    probed += 1",
  "    try:",
  "        if pairs.get(h.title):",
  "            got = shelf_mod.probe(look_lang, h.title, look_other, pairs[h.title], ws_fetch)",
  "        else:",
  // No counterpart on the wiki is a fact about the wiki's links, not about the
  // book. Ask the second library whose book this is, and offer what it has —
  // offered, never asserted: only the reader knows it is the same book.
  "            got = shelf_mod.probe_alone(look_lang, h.title, ws_fetch)",
  "            author = got.get('author') or ''",
  "            if author not in by_author:",
  "                by_author[author] = [{'path': b.path, 'title': b.title, 'translator': b.translator}",
  "                                     for b in se.by_author(author, ws_fetch)]",
  "            got['alternatives'] = by_author[author]",
  "    except Exception as err:",
  "        got = {'page': h.title, 'otherPage': pairs.get(h.title), 'buildable': False, 'why': str(err)}",
  "    got['title'] = h.title",
  "    js_probe(json.dumps(got))",
  "json.dumps({'hits': len(found.hits), 'probed': probed, 'more': found.more})",
].join("\n");

// One page, done for real, so the reader sees the prose before paying for the
// book — and weighed while it is here, so the book is priced by what this model
// actually charges rather than by a constant that fits some other model.
const SAMPLE = [
  "MODEL = model_id",
  LOAD,
  "import json",
  "from biread.sample import sample_translate, sample_align, sample_gloss, body_chars",
  "client = None",
  "if pub_chapters and route != 'translate':",
  indent(EMBEDDER),
  "    s = sample_align(orig_chapters, pub_chapters, embedder.embed, sample_index)",
  "    if want_gloss:",
  indent(indent(CHAT_CLIENT)),
  "else:",
  indent(CHAT_CLIENT),
  "    s = sample_translate(orig_chapters, client, cfg, target.name, sample_index)",
  "gloss_cost = sample_gloss(s.source, client, cfg, target.name) if (want_gloss and client) else None",
  // The book's own size comes back with the page, measured over the same trimmed
  // body the page was cut from — front matter counted on one side and not the
  // other would tilt every scaling done from it.
  "book_chars = body_chars(orig_chapters)",
  "json.dumps({'index': s.index, 'total': s.total, 'source': s.source, 'target': s.target, 'cost': s.cost, 'glossCost': gloss_cost, 'chars': sum(len(p) for p in s.source), 'bookChars': book_chars})",
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
  "if route != 'translate':",
  "    out['paragraphs'] = sum(len(c.paragraphs) for c in orig_chapters)",
  "else:",
  // Against this reader's own cache, so a book half built in an earlier session
  // is priced at what is left of it rather than at the whole.
  "    e = est_tr(orig_chapters, cache, cfg, target.name)",
  "    out.update(paragraphs=e.total, pending=e.pending, translate_cost=e.cost)",
  "if want_gloss:",
  "    from biread.gloss import opening",
  "    g = est_gl(orig_chapters, cache, cfg.for_glossing(), target.name,",
  "               opening(orig_chapters) if gloss_opening else None)",
  "    out.update(gloss_cost=g.cost or 0.0, gloss_done=g.cached, gloss_total=g.total)",
  "out['cost'] = (out['translate_cost'] or 0.0) + (out['gloss_cost'] or 0.0)",
  "json.dumps(out)",
].join("\n");

// The book, up to but not including its glosses. What is left of the build is
// run from `glossInParallel` below and finished by `build_end`.
const BUILD = [
  "MODEL = model_id",
  LOAD,
  "from biread.build import draft_reader",
  CHAT_CLIENT,
  "_JOB.update(client=client, cache=cache, cfg=cfg.for_glossing(), target=target)",
  "_JOB['draft'] = draft_reader(title=title, chapters=orig_chapters, client=client, cache=cache, cfg=cfg, target=target, published_chapters=pub_chapters, on_progress=lambda s, d, t: js_progress(s, d, t), on_text=lambda pairs: js_text(json.dumps(pairs)))",
].join("\n");

// Align-only: no translation. Match a brought published edition to the French by
// meaning, with an embedding model — BGE-M3 on a local Ollama (free) or a cloud
// model (pennies). The published English becomes the single reading column.
const ALIGN = [
  "MODEL = model_id",
  LOAD,
  "from biread.build import draft_aligned",
  EMBEDDER,
  // Glossing is chat-model work the embedding key usually also reaches, so the
  // hover survives the route that translates nothing.
  "client = None",
  "if want_gloss:",
  indent(CHAT_CLIENT),
  "_JOB.update(client=client, cache=cache, cfg=cfg.for_glossing(), target=target)",
  // Until the first chapter lands there is no match to show, so the left page
  // turns through the real book on the count alone and the right says it is
  // waiting. From the first chapter on, the spread shows the pairs themselves.
  "js_seed(json.dumps([[p, ''] for c in orig_chapters for p in c.paragraphs][:400]))",
  // The matching is the long part of this route, and it is kept chapter by
  // chapter in the same drawer the translations and glosses are: a build stopped
  // halfway through comes back to the chapters it has left rather than the book.
  "_JOB['draft'] = draft_aligned(title=title, chapters=orig_chapters, published_chapters=pub_chapters, embed=embedder.embed, target=target, repair_client=client, cache=cache, embed_id=embed_model, on_progress=lambda s, d, t: js_progress(s, d, t), on_text=lambda pairs: js_text(json.dumps(pairs)))",
].join("\n");

// The whole of a build: the book, then its glosses, then the type set.
async function buildBook(script, m) {
  await pyodide.runPythonAsync(script);
  if (m.gloss && m.key) {
    const task = JSON.parse(pyodide.runPython("gloss_task()"));
    const used = task.batches.length
      ? await glossInParallel(task, {
          provider: m.provider || "anthropic", baseUrl: m.baseUrl || "",
          key: m.key, model: m.model, local: !!m.local,
        })
      : { in: 0, out: 0 };
    pyodide.runPython(`gloss_end(${used.in}, ${used.out})`);
  }
  return JSON.parse(pyodide.runPython("build_end()"));
}

self.onmessage = async (e) => {
  await ready;
  const m = e.data;
  try {
    // What an earlier session already paid for on this book, handed back before
    // anything is priced or built.
    if (m.type === "restore") {
      pyodide.globals.set("work_key", m.key);
      pyodide.globals.set("restore_json", JSON.stringify(m.entries || {}));
      postMessage({
        type: "restored", key: m.key,
        held: pyodide.runPython("restore(work_key, restore_json)"),
      });
      return;
    }
    const names = [m.origName, m.pubName].filter(Boolean).join(" ").toLowerCase();
    if (names.includes(".pdf")) {
      await pyodide.runPythonAsync("import micropip\nawait micropip.install('pypdf')");
    }
    const origPath = m.orig ? write("orig_" + m.origName, m.orig) : null;
    const pubPath = m.pub ? write("pub_" + m.pubName, m.pub) : null;
    pyodide.globals.set("orig_path", origPath);
    pyodide.globals.set("pub_path", pubPath);
    // The names the reader chose, kept apart from the paths, which prefix them
    // so two uploads cannot collide on disk.
    pyodide.globals.set("orig_name", m.origName || "");
    pyodide.globals.set("pub_name", m.pubName || "");
    pyodide.globals.set("lang_key", m.lang || "en");
    // Which slot of paid-for work this book uses. The page names it after the
    // book's own text and the language wanted, since the same paragraphs in
    // another language are another translation.
    pyodide.globals.set("work_key", m.workKey || "loose");
    pyodide.globals.set("want_gloss", !!m.gloss);
    // How much of the hover the build itself makes: the whole book, or its
    // opening with the rest left to the reader. How long an opening is is
    // `biread.gloss.opening`'s to say, since the paragraphs are on this side.
    pyodide.globals.set("gloss_opening", !!m.glossOpening);
    pyodide.globals.set("api_key", m.key || "");
    pyodide.globals.set("title", m.title || "book");
    pyodide.globals.set("model_id", m.model || "claude-sonnet-5");
    pyodide.globals.set("route", m.route || "translate");
    pyodide.globals.set("sample_index", m.sampleIndex || 0);
    // Provider, its base URL, and the model's live price (input/output $ per Mtok)
    // all come from the page, which knows what the reader picked and what it costs.
    pyodide.globals.set("provider", m.provider || "anthropic");
    pyodide.globals.set("base_url", m.baseUrl || "");
    // A build on the reader's own machine reaches its model through OpenRouter's
    // wire shape at a local address, so the provider it names is not the one the
    // finished book must send a reader to.
    pyodide.globals.set("local_engine", !!m.local);
    pyodide.globals.set("price_in", m.priceIn || 0);
    pyodide.globals.set("price_out", m.priceOut || 0);
    pyodide.globals.set("embed_model", m.embedModel || "bge-m3");
    // A shelf book stands in for the two uploads: once fetched it is kept under
    // this key, and every later stage reads it exactly where it reads a file.
    pyodide.globals.set("shelf_key", m.shelfKey || null);
    pyodide.globals.set("shelf_slug", m.shelfSlug || null);
    pyodide.globals.set("translation_index", m.translationIndex || 0);
    pyodide.globals.set("found_json", m.found ? JSON.stringify(m.found) : "null");
    pyodide.globals.set("query", m.query || "");
    pyodide.globals.set("look_lang", m.lookLang || "fr");
    pyodide.globals.set("look_other", m.lookOther || "en");
    pyodide.globals.set("look_offset", m.lookOffset || 0);
    pyodide.globals.set("js_hits", (found) => postMessage({ type: "hits", ...JSON.parse(found) }));
    pyodide.globals.set("js_probe", (got) => postMessage({ type: "probe", data: JSON.parse(got) }));
    // Live from here on: reading a PDF reports its pages during pricing and the
    // free build alike, not only while translating.
    pyodide.globals.set("js_progress", (s, d, t) => postMessage({ type: "progress", stage: s, done: d, total: t }));
    // Finished prose, batch by batch, so the progress spread fills with the book
    // being made rather than a placeholder.
    pyodide.globals.set("js_text", (pairs) => postMessage({ type: "text", pairs: JSON.parse(pairs) }));
    // Each entry the build pays for, as it lands, for the page to keep. A build
    // that is interrupted — a closed tab, a machine switched off — then resumes
    // from here rather than buying the same paragraphs twice.
    pyodide.globals.set("js_cached", (entries) => postMessage({ type: "cached", key: m.workKey || "loose", entries: JSON.parse(entries) }));
    // The book before any of it is matched: what the left page turns through
    // while the first chapter is still being read.
    pyodide.globals.set("js_seed", (pairs) => postMessage({ type: "seed", pairs: JSON.parse(pairs) }));

    if (m.type === "shelf") {
      postMessage({ type: "inspected", data: JSON.parse(await pyodide.runPythonAsync(SHELF)) });
    } else if (m.type === "lookup") {
      postMessage({ type: "looked", data: JSON.parse(await pyodide.runPythonAsync(LOOKUP)) });
    } else if (m.type === "inspect") {
      postMessage({ type: "inspected", data: JSON.parse(await pyodide.runPythonAsync(INSPECT)) });
    } else if (m.type === "sample") {
      postMessage({ type: "sample", data: JSON.parse(await pyodide.runPythonAsync(SAMPLE)) });
    } else if (m.type === "estimate") {
      postMessage({ type: "estimate", data: JSON.parse(await pyodide.runPythonAsync(ESTIMATE)) });
    } else if (m.type === "build") {
      postMessage({ type: "done", ...(await buildBook(BUILD, m)) });
    } else if (m.type === "align") {
      postMessage({ type: "done", ...(await buildBook(ALIGN, m)) });
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
