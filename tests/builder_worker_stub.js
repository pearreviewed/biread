// Stands in for web/worker.js while the builder's own screens are under test.
//
// The builder reaches its engine by a relative `new Worker("worker.js")`, so
// serving this file beside builder.html swaps the engine out with no seam in the
// page itself — the code under test is the shipped code, unmodified.
//
// Tests steer it by what they put *in* the uploaded file: a book whose text
// begins `SCENARIO:` followed by JSON overrides any of the replies below. That
// keeps the control channel inside the fixture, where a reader would never meet
// it, instead of in the builder.

const LANGS = {
  default: "en",
  items: [["en", "English"], ["es", "Spanish"], ["de", "German"]],
};

const SOURCE = [
  "Il y avait dans une planète qui tourne autour de l'étoile nommée Sirius, un jeune homme de beaucoup d'esprit.",
  "Il ne parle, en effet, que le hollandais.",
  "Après s'être reposés quelque temps, ils mangèrent à leur déjeuner deux montagnes.",
];
const TARGET = [
  "On a planet that orbits the star named Sirius there lived a young man of great intelligence.",
  "He speaks nothing but Dutch, in fact.",
  "After resting awhile, they ate two mountains for their breakfast.",
];

const DEFAULTS = {
  inspect: {
    orig: { title: "Micromégas", author: "Voltaire", language: "fr", pages: null, paragraphs: 34, chars: 38974 },
    pub: { title: "Micromegas", author: "Peter Phalen", language: "en", pages: null, paragraphs: 132, chars: 41000 },
  },
  sample: { total: 12, cost: 0.0009, glossCost: 0.0055, chars: 3102, bookChars: 38974 },
  estimate: { paragraphs: 41, pending: 41, translate_cost: 0.0147, gloss_cost: 0.0561 },
  build: { spent: 0.116, html: "<!doctype html><title>Micromégas</title>" + "x".repeat(400000) },
  progress: [["read-orig", 1, 1], ["translate", 12, 41], ["gloss", 20, 34]],
  failOn: null,   // "inspect" | "sample" | "estimate" | "build" | "align"
  error: "the model refused the request",
};

function scenario(bytes) {
  if (!bytes) return {};
  const text = new TextDecoder().decode(bytes.slice(0, 4000));
  if (!text.startsWith("SCENARIO:")) return {};
  try {
    return JSON.parse(text.slice("SCENARIO:".length).split("\n---")[0]);
  } catch (e) {
    return {};
  }
}

postMessage({ type: "ready", langs: LANGS });

self.onmessage = (e) => {
  const m = e.data;
  const s = { ...DEFAULTS, ...scenario(m.orig) };

  if (s.failOn === m.type) {
    postMessage({ type: "error", error: s.error, during: m.type });
    return;
  }

  if (m.type === "inspect") {
    postMessage({ type: "inspected", data: { orig: s.inspect.orig, pub: m.pub ? s.inspect.pub : null } });
    return;
  }

  if (m.type === "sample") {
    const index = (m.sampleIndex || 0) % s.sample.total;
    postMessage({
      type: "sample",
      data: {
        index, total: s.sample.total,
        source: SOURCE, target: s.sample.blankTarget ? ["", "", ""] : TARGET,
        cost: m.route === "align" ? null : s.sample.cost,
        glossCost: m.gloss ? s.sample.glossCost : null,
        chars: s.sample.chars, bookChars: s.sample.bookChars,
      },
    });
    return;
  }

  if (m.type === "estimate") {
    const e_ = s.estimate;
    const translate = m.route === "align" ? null : e_.translate_cost;
    const gloss = m.gloss ? e_.gloss_cost : null;
    postMessage({
      type: "estimate",
      data: {
        model: m.model, paragraphs: e_.paragraphs, pending: e_.pending,
        translate_cost: translate, gloss_cost: gloss,
        cost: (translate || 0) + (gloss || 0),
      },
    });
    return;
  }

  if (m.type === "build" || m.type === "align") {
    // Progress and prose in the order the real engine sends them, so the page
    // fills exactly as it would on a paid run.
    postMessage({ type: "text", pairs: [[SOURCE[0], TARGET[0]]] });
    for (const [stage, done, total] of s.progress) {
      postMessage({ type: "progress", stage, done, total });
    }
    postMessage({ type: "text", pairs: [[SOURCE[1], TARGET[1]]] });
    postMessage({ type: "done", html: s.build.html, spent: m.type === "align" ? null : s.build.spent });
  }
};
