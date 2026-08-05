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

// Three books, enough to exercise the shelf's own shapes: one read through, one
// with two translations, one nobody has vouched for.
const SHELF = {
  measured: "2026-07-30",
  perMinute: 390,
  filters: [
    { key: "read", label: "Read through", slugs: ["candide"] },
    { key: "several", label: "More than one translation", slugs: ["micromegas"] },
  ],
  books: [
    {
      slug: "candide", title: "Candide, ou l’Optimisme", author: "Voltaire",
      page: "Candide, ou l’Optimisme", lang: "fr", other: "en",
      chapters: 30, paragraphs: 469, minutes: 3, tokens: 95916,
      note: "Smollett put this into English in Voltaire’s own century.",
      summary: "A young man raised to believe this the best of all possible "
        + "worlds is thrown out of the castle and around the earth.",
      // The other published book: approved and handed over, but without glosses,
      // which the card says in two words and does not sell.
      prebuilt: {
        href: "books/candide.html", filename: "Candide - bilingual reader.html",
        english: "Smollett · 1920", approved: "2026-08-01", bytes: 614583,
        paragraphs: 469, translated: 464, glossed: 0,
        published: false, solo: true, formats: [],
      },
      readThrough: true, coverage: 0.989, added: false,
      english: "Smollett · 1920", abridged: false, chaptered: true, counts: [30, 30],
      translations: [{ page: "Candide", label: "Smollett · 1920", chapters: 30 }],
    },
    {
      slug: "micromegas", title: "Micromégas", author: "Voltaire",
      page: "Micromégas", lang: "fr", other: "en",
      chapters: 7, paragraphs: 74, minutes: 1, tokens: 19812,
      note: "Two English versions, and they are shaped differently.",
      summary: "A traveller from a star of Sirius picks up a Saturnian on the "
        + "way past and finds the Earth.",
      readThrough: false, coverage: null, added: false,
      english: "Phalen", abridged: false, chaptered: true, counts: [7, 7],
      translations: [
        { page: "Micromegas (Phalen)", label: "Phalen", chapters: 7 },
        { page: "The Works of Voltaire/Volume 3/Micromegas", label: "Fleming · 1906", chapters: 1 },
      ],
      // The one book here that was built, read and approved. Everything in this
      // block is measured off the finished file by web/build.py; the shape is
      // copied from what it writes, and the card may claim nothing else.
      prebuilt: {
        href: "books/micromegas.html", filename: "Micromégas - bilingual reader.html",
        english: "Phalen", approved: "2026-08-01", bytes: 1142524,
        paragraphs: 34, translated: 34, glossed: 34,
        published: true, solo: false, formats: ["epub", "pdf"],
      },
    },
    {
      slug: "80days", title: "Le Tour du monde en quatre-vingts jours", author: "Verne",
      page: "Le Tour du monde en quatre-vingts jours", lang: "fr", other: "en",
      chapters: 37, paragraphs: 1892, minutes: 9, tokens: 191742,
      // No summary: the shape of a book somebody looked up rather than curated,
      // whose card has nothing to open on.
      note: "Towle cut as he went, so some of the French will face an empty page.",
      readThrough: false, coverage: null, added: false,
      english: "Towle · 1873", abridged: true, chaptered: true, counts: [37, 37],
      translations: [{ page: "Around the World in Eighty Days (Towle)", label: "Towle · 1873", chapters: 37 }],
    },
  ],
};

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
  return parse(text);
}
function parse(text) {
  if (!text || !text.startsWith("SCENARIO:")) return {};
  try {
    return JSON.parse(text.slice("SCENARIO:".length).split("\n---")[0]);
  } catch (e) {
    return {};
  }
}

// The shelf takes no upload, so its scenarios ride in on the one thing a reader
// does type there: the lookup query. Flags set that way stick for the session.
let standing = {};

postMessage({ type: "ready", langs: LANGS, shelf: SHELF });

self.onmessage = (e) => {
  const m = e.data;
  Object.assign(standing, parse(m.query));
  const s = { ...DEFAULTS, ...standing, ...scenario(m.orig) };

  if (s.failOn === m.type) {
    postMessage({ type: "error", error: s.error, during: m.type });
    return;
  }

  if (m.type === "shelf") {
    const book = SHELF.books.find((b) => b.slug === m.shelfSlug);
    const version = book && book.translations[m.translationIndex || 0];
    postMessage({
      type: "inspected",
      data: {
        orig: { title: book ? book.title : m.found.title, author: book ? book.author : m.found.author,
                language: "fr", pages: null, paragraphs: book ? book.paragraphs : 700,
                chars: 184197, chapters: book ? book.chapters : 40 },
        pub: { title: version ? version.page : m.found.otherPage,
               author: version ? version.label : m.found.translator,
               language: "en", pages: null, paragraphs: 689, chars: 199468,
               chapters: version ? version.chapters : 40 },
      },
    });
    return;
  }

  // A search that finds nothing is the honest half of this screen, so it is as
  // reachable in the stub as it is in life. So is a search that finds more works
  // than one page holds: the lookup used to cap both the works it showed and the
  // ones it checked, silently, and every earlier fixture returned exactly one
  // page of exactly two — the one regime where that code is fine.
  const LOOK_PAGE = 4;
  function catalogue(query) {
    if (query.includes("camus") || query.includes("nothing")) return [];
    if (query.includes("zola")) {
      return Array.from({ length: 7 }, (_, i) => ({
        title: "Zola " + (i + 1), snippet: "Émile Zola", counterpart: "Zola " + (i + 1) + " (Ellis)",
        // The last one answers nothing, so a card with no probe behind it is
        // reachable without a control the reader could ever meet.
        silent: i === 6,
      }));
    }
    if (query.includes("rêve") || query.includes("reve")) {
      // The live shape of the wiki's sparse interwiki links: an original with no
      // counterpart named, whose author does have editions in the other library.
      return [{ title: "Le Rêve", snippet: "Zola", counterpart: null, alternatives: [
        { path: "/ebooks/emile-zola/the-dream/eliza-chase", title: "The Dream", translator: "Eliza Chase" },
        { path: "/ebooks/emile-zola/germinal/havelock-ellis", title: "Germinal", translator: "Havelock Ellis" },
      ] }];
    }
    return [
      { title: "Germinal", snippet: "Émile Zola Germinal", counterpart: "Germinal (Ellis)" },
      { title: "Germinie Lacerteux", snippet: "Goncourt", counterpart: null, author: "Goncourt" },
    ];
  }

  if (m.type === "lookup") {
    const works = catalogue((m.query || "").toLowerCase());
    const offset = m.lookOffset || 0;
    const hits = works.slice(offset, offset + LOOK_PAGE);
    postMessage({
      type: "hits",
      hits: hits.map(({ silent, alternatives, author, ...h }) => h),
      more: Math.max(0, works.length - offset - LOOK_PAGE),
    });
    let probed = 0;
    for (const hit of hits.filter((h) => !h.silent)) {
      probed += 1;
      // No counterpart on the wiki: the original alone, and whatever the second
      // library has by that author, offered for the reader to confirm.
      postMessage({
        type: "probe",
        data: hit.counterpart ? {
          title: hit.title, page: hit.title, otherPage: hit.counterpart,
          chapters: 40, otherChapters: 40, shape: "chapters", otherShape: "translation",
          author: "Zola", english: "Ellis · 1894", translator: "Havelock Ellis",
          year: "1894", buildable: true,
        } : {
          title: hit.title, page: hit.title, chapters: 16, shape: "chapters",
          author: hit.author || "Émile Zola", buildable: true,
          alternatives: hit.alternatives || [],
        },
      });
    }
    postMessage({ type: "looked", data: { hits: hits.length, probed } });
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
        cost: m.route === "translate" ? s.sample.cost : null,
        glossCost: m.gloss ? s.sample.glossCost : null,
        chars: s.sample.chars, bookChars: s.sample.bookChars,
      },
    });
    return;
  }

  if (m.type === "estimate") {
    const e_ = s.estimate;
    const translate = m.route === "translate" ? e_.translate_cost : null;
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
