(function () {
  'use strict';

  var DATA;
  try {
    DATA = JSON.parse(document.getElementById('book-data').textContent);
  } catch (e) {
    document.getElementById('stage-wrap').innerHTML =
      '<div class="loading-msg">This file is damaged — rebuild it with biread.</div>';
    return;
  }

  var PAIRS = DATA.pairs;
  var CHAPTERS = DATA.chapters;
  var PUBLISHED = !!DATA.publishedAvailable;
  var SOLO = !!DATA.solo;
  // Formats built alongside this book, in menu order. The bytes live in separate
  // <script> blobs (read only on download); this just says what to offer.
  var DOWNLOADS = DATA.downloads || [];
  var DOWNLOAD_LABELS = {
    epub: { title: 'EPUB', sub: 'For e-readers' },
    pdf: { title: 'PDF', sub: 'Print · side by side' }
  };
  // Every functional label comes from the target-language table in the book
  // data; LANG is the translated column's language, for hyphenation. The markup
  // ships English as a fallback, tagged with data-i18n keys.
  var UI = DATA.ui || {};
  var LANG = DATA.lang || 'en';
  // Reader-side correction of the AI translation (opt-in --revise). Null unless
  // the build embedded it; every branch below is a no-op when it stays null.
  var REVISE = (DATA.revise && DATA.revise.enabled) ? DATA.revise : null;
  // Glossing a paragraph at a time, on the reader's own key, for a book that was
  // published without glosses. Carries the whole protocol — the prompt, the
  // field separator, and what French itself contributes — so the judgement below
  // reads the same data biread/gloss.py reads. Null on a book built with glosses
  // already in it, and on any book that never enabled this.
  var GLOSS = (DATA.gloss && DATA.gloss.enabled) ? DATA.gloss : null;
  // The corner tags. The source is always French — the masthead and the left
  // column's lang say so — and the target follows the build's language.
  var SOURCE_TAG = 'FR';
  var TARGET_TAG = (LANG.split('-')[0] || 'en').toUpperCase();
  function i18n(key) { return UI[key] != null ? UI[key] : ''; }
  function applyStaticLabels() {
    var set = function (attr, apply) {
      var nodes = document.querySelectorAll('[' + attr + ']');
      for (var i = 0; i < nodes.length; i++) {
        var value = i18n(nodes[i].getAttribute(attr));
        if (value) apply(nodes[i], value);
      }
    };
    set('data-i18n', function (n, v) { n.textContent = v; });
    set('data-i18n-aria', function (n, v) { n.setAttribute('aria-label', v); });
    set('data-i18n-title', function (n, v) { n.setAttribute('title', v); });
  }
  // Below this the two columns get too cramped to read and the reader falls back
  // to a single stacked column. Kept low enough that a partly-sized laptop window
  // still gets the two-page spread — only phones and very narrow windows stack.
  var MOBILE_BREAKPOINT = 640;
  // The open-book spread is sized to the biggest box of this aspect that fits the
  // stage both ways (see sizeBook). 7:5 is two ~0.7 pages — a real open book — and
  // fills a wide laptop far better than a squarer spread without over-long lines.
  var SPREAD_RATIO = 7 / 5;
  var WIDTH_FILL = 0.94;   // leave a little desk at the sides on a wide-short window
  var MAX_BOOK_W = 1500;   // absolute cap, so the book stays a book on a huge screen
  var TURN_MS = 600;
  var FADE_MS = 150;
  var STORE_VERSION = 2;
  var LAYOUT_RETRIES = 50; // ~6s of waiting for a usable page box

  document.getElementById('book-title-label').textContent = DATA.titleFr;

  // A section is a run of pairs that starts a fresh spread: each chapter forces
  // a page break, so pagination can run one section at a time.
  var SECTIONS = (function () {
    var starts = [0];
    CHAPTERS.forEach(function (c) {
      if (starts.indexOf(c.pair) === -1) starts.push(c.pair);
    });
    starts.sort(function (a, b) { return a - b; });
    var out = [];
    for (var i = 0; i < starts.length; i++) {
      var start = starts[i];
      var end = i + 1 < starts.length ? starts[i + 1] : PAIRS.length;
      if (start >= end) continue;
      var chapter = null;
      CHAPTERS.forEach(function (c) { if (c.pair === start) chapter = c; });
      out.push({ start: start, end: end, chapter: chapter });
    }
    return out;
  })();

  var S = {
    mobile: window.innerWidth < MOBILE_BREAKPOINT,
    fontScale: 1,
    blurEnglish: false,
    activePair: -1,
    source: 'translation',
    spreadIndex: 0,
    bookmarks: [],
    resumePair: null,
    resumeFrac: 0,
    turn: null,
    fade: false,
    ready: false,
    chapOpen: false,
    bmOpen: false,
    infoOpen: false,
    dlOpen: false
  };

  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var spreads = [];
  var paginated = 0; // sections laid out so far; always the lowest N, in order
  // When a reflow (font or window change) rebuilds the grid, the reader's
  // position is forced to start a spread so their line stays at the top of the
  // page instead of being pulled up into the tail of the one before. Null for
  // the natural, position-independent grid the book first opens with.
  var forcedBreak = null;
  var backgroundTimer = null;
  var transitionTimer = null;
  var probe = {};
  var view = {}; // the mounted book: page nodes, ribbon host
  // Reader corrections to the generated English, keyed by source hash, plus the
  // reader's own key (in memory) and the floating correction UI's live state.
  var overrides = {};
  var apiKey = '';
  var reviseCtl = null;
  var keyPanel = null;
  var bought = {};      // glosses this reader paid for, by paragraph hash
  var glossBusy = false;
  var reviseTarget = null;
  var reviseBusy = false;
  var undoStack = []; // this session's corrections, for Cmd/Ctrl+Z

  // Type scales with the book, so a smaller book keeps the same number of
  // characters per line instead of turning into a narrow ribbon of text.
  // 1140px of book lands near 20px; the cap lets a wide-screen spread grow a
  // little more instead of flattening into over-long lines. Kept deliberately
  // unhurried — the page should have air, not fill wall to wall.
  function fpx() {
    var width = view.book ? view.book.getBoundingClientRect().width : 1060;
    var base = Math.max(15, Math.min(22, width / 57));
    return Math.round(base * S.fontScale);
  }

  function applyFontSize() {
    document.documentElement.style.setProperty('--fpx', fpx() + 'px');
  }

  // Slack between what the probe measures and what the real page draws. A
  // column's offsetHeight omits its last paragraph's bottom margin, but the page
  // still draws it, so the page stands that much taller than the probe reported.
  // Reserve about a line: enough for that margin (0.5em) and a pixel or two of
  // integer rounding, and it scales with the type, so enlarging the font never
  // tips a page into scrolling.
  function fitMargin() {
    return Math.max(8, Math.round(fpx() * 0.75));
  }

  // Size the desktop spread to the largest SPREAD_RATIO box that fits the stage
  // both ways: height-bound on a wide window (fills the height, centred with a
  // little desk either side), width-bound on a tall one, capped on a huge screen.
  // Height is recomputed from the final width, so no cap can flatten the ratio.
  // Mobile is one stacked column, left to CSS.
  function sizeBook() {
    if (!view.book || S.mobile) return;
    var stage = document.getElementById('stage-wrap');
    var cs = getComputedStyle(stage);
    var availW = stage.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    var availH = stage.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    if (availW < 1 || availH < 1) return;
    var w = Math.min(availW * WIDTH_FILL, availH * SPREAD_RATIO, MAX_BOOK_W);
    view.book.style.width = w + 'px';
    view.book.style.height = w / SPREAD_RATIO + 'px';
  }

  // Measure the stage rather than trusting window.innerWidth, which some
  // embedded/preview browser contexts report as 0 or fail to update on resize.
  function availableWidth() {
    var stage = document.getElementById('stage-wrap');
    return (stage && stage.clientWidth) || window.innerWidth ||
      document.documentElement.clientWidth;
  }

  function isMobileWidth() { return availableWidth() < MOBILE_BREAKPOINT; }

  // The header wraps to two or three rows on narrow screens, so overlays cannot
  // assume a fixed offset from the top.
  function measureHeader() {
    var header = document.getElementById('app-header');
    if (header) {
      document.documentElement.style.setProperty('--header-h', header.offsetHeight + 'px');
    }
  }

  // ---------- storage ----------
  function lsKey(k) { return 'biread:' + DATA.slug + ':' + k; }
  function lsGet(k) {
    try {
      var raw = localStorage.getItem(lsKey(k));
      if (raw == null) return null;
      var value = JSON.parse(raw);
      // Positions are stored as pair indices. Anything older recorded spread
      // indices, which move with font size and window width — ignore it.
      return value && value.v === STORE_VERSION ? value : null;
    } catch (e) { return null; }
  }
  function lsSet(k, v) {
    try { localStorage.setItem(lsKey(k), JSON.stringify(v)); } catch (e) {}
  }

  // Corrections are per book (slug-namespaced, like bookmarks). The key is per
  // provider, not per book — a reader's Anthropic key works for any Anthropic
  // edition — and lives in localStorage when remembered, sessionStorage when not.
  function loadOverrides() {
    var stored = lsGet('overrides');
    overrides = stored && stored.byHash ? stored.byHash : {};
  }
  function saveOverrides() {
    lsSet('overrides', { v: STORE_VERSION, byHash: overrides });
  }
  function hasOverride(i) {
    var h = PAIRS[i].h;
    return !!(h && overrides[h] && overrides[h].base === PAIRS[i].en);
  }
  // Keyed by provider, not by feature: one OpenRouter key rewrites a phrase and
  // glosses a paragraph equally well, so a reader who has given it once has
  // given it. The name is historical — correction wanted a key first — and
  // renaming it would only throw away the keys readers have already saved.
  function keyName(cfg) {
    var of = cfg || REVISE || GLOSS;
    return 'biread:revise-key:' + (of ? of.provider : '');
  }
  function loadKey(cfg) {
    var name = keyName(cfg);
    try { return localStorage.getItem(name) || sessionStorage.getItem(name) || ''; }
    catch (e) { return ''; }
  }
  function storeKey(key, remember, cfg) {
    var name = keyName(cfg);
    try {
      localStorage.removeItem(name);
      sessionStorage.removeItem(name);
      if (key) (remember ? localStorage : sessionStorage).setItem(name, key);
    } catch (e) {}
  }

  // ---------- content ----------
  function englishText(i) {
    if (S.source === 'published' && PAIRS[i].pub) return PAIRS[i].pub;
    return generatedEnglish(i);
  }

  // The generated English with any reader correction applied. Both painting and
  // pagination read the AI translation through this, so a fix changes what is
  // measured and the page reflows to fit it. An override applies only while the
  // built-in translation still matches what it was made against, so a rebuild
  // that retranslates the paragraph drops a now-stale fix rather than pasting it
  // onto different prose. The published column never routes through here.
  function generatedEnglish(i) {
    var pair = PAIRS[i];
    if (REVISE && pair.h) {
      var ov = overrides[pair.h];
      if (ov && ov.base === pair.en) return ov.text;
    }
    return pair.en;
  }

  function headingNode(chapter, lang) {
    var head = document.createElement('div');
    head.className = 'chapter-heading';
    head.lang = lang === 'en' ? 'en' : 'fr';
    var eyebrow = document.createElement('div');
    eyebrow.className = 'ch-eyebrow';
    eyebrow.textContent = lang === 'en' ? chapter.enEyebrow : chapter.frEyebrow;
    var title = document.createElement('div');
    title.className = 'ch-title';
    title.textContent = lang === 'en' ? chapter.enTitle : chapter.frTitle;
    var rule = document.createElement('div');
    rule.className = 'ch-rule';
    head.appendChild(eyebrow);
    head.appendChild(title);
    head.appendChild(rule);
    return head;
  }

  function publishedText(i) { return PAIRS[i].pub || PAIRS[i].en; }

  function paragraphNode(i, side, text, continued) {
    var p = document.createElement('p');
    p.className = 'pair pair-' + side;
    p.dataset.pair = i;
    // `hyphens: auto` breaks words using the element's language. Without this
    // the English column inherits lang="fr" from <html> and gets hyphenated
    // with French syllabification ("mee-ting" instead of "meet-ing") — wrong
    // typography, and wrong line counts feeding back into pagination.
    p.lang = side === 'en' ? LANG : 'fr';
    p.textContent = text;
    // A paragraph resumed from the previous page is not a new paragraph, so it
    // starts flush rather than indented.
    if (continued) p.classList.add('continued');
    if (side === 'en' && S.blurEnglish && S.activePair !== i) p.classList.add('blurred');
    return p;
  }

  // The French is glossed here exactly as the two-page layout glosses it, so a
  // phone reader can tap a phrase for its meaning — the same units, the same tap
  // that pins the tooltip. from/to (not a pre-sliced string) so `glossedNode` can
  // place each unit by its offset into the paragraph.
  function mobilePairNode(i, from, to, english, continued) {
    var box = document.createElement('div');
    box.className = 'mobile-pair';
    box.dataset.pair = i;
    box.appendChild(glossedNode(i, from, to, continued));
    box.appendChild(paragraphNode(i, 'en', english, continued));
    return box;
  }

  // ---------- positions ----------
  // A position is a paragraph and how far through it: {p: index, f: 0..1}. A
  // paragraph too tall for one page continues onto the next, so a spread spans
  // two positions rather than covering a whole number of paragraphs.
  function position(p, f) { return { p: p, f: f }; }

  // a strictly before b in reading order. The epsilon keeps near-equal fractions
  // from forcing a zero-height or duplicate spread boundary.
  function posBefore(a, b) {
    return a.p !== b.p ? a.p < b.p : a.f + 1e-6 < b.f;
  }

  // Snap forward to a word boundary so a split never cuts through a word.
  function sliceAt(text, fraction) {
    if (fraction <= 0) return 0;
    if (fraction >= 1) return text.length;
    var space = text.indexOf(' ', Math.round(text.length * fraction));
    return space === -1 ? text.length : space + 1;
  }

  function textSpan(text, from, to) {
    return text.slice(sliceAt(text, from), sliceAt(text, to)).trim();
  }

  // Walk the parts of each paragraph a spread shows, in reading order.
  function eachPart(spread, callback) {
    for (var p = spread.from.p; p <= spread.to.p && p < PAIRS.length; p++) {
      var from = p === spread.from.p ? spread.from.f : 0;
      var to = p === spread.to.p ? spread.to.f : 1;
      if (to <= from) continue;
      callback(p, from, to, from > 0);
    }
  }

  function spreadCoversPair(spread, pair) {
    if (!spread || spread.from.p > pair) return false;
    // `to` is the exclusive end — it is where the next spread begins. The
    // paragraph at to.p sits on this spread only when the spread stops partway
    // through it (to.f > 0); when to.f is 0 that paragraph opens the next spread,
    // not this one. Without this the spread before a bookmark, whose `to` lands
    // on the bookmarked paragraph's first character, also lit up the ribbon.
    return pair < spread.to.p || (pair === spread.to.p && spread.to.f > 0);
  }

  function dividerNode() {
    var d = document.createElement('div');
    d.className = 'mobile-divider';
    return d;
  }

  // Trim the slice to a word, then report the character range it occupies in
  // the paragraph — units are stored as offsets into that same string.
  function spanRange(text, from, to) {
    var start = sliceAt(text, from);
    var end = sliceAt(text, to);
    while (start < end && /\s/.test(text[start])) start++;
    while (end > start && /\s/.test(text[end - 1])) end--;
    return [start, end];
  }

  // A unit that straddles a page break is rendered as plain text rather than
  // half a hover target on each side.
  function glossedNode(pair, from, to, continued) {
    var text = PAIRS[pair].fr;
    var units = PAIRS[pair].units;
    var range = spanRange(text, from, to);
    var node = paragraphNode(pair, 'fr', '', continued);
    if (!units) {
      node.textContent = text.slice(range[0], range[1]);
      return node;
    }
    var cursor = range[0];
    for (var i = 0; i < units.length; i++) {
      var unit = units[i];
      if (unit[0] < cursor || unit[1] > range[1]) continue;
      if (unit[0] > cursor) {
        node.appendChild(document.createTextNode(text.slice(cursor, unit[0])));
      }
      var span = document.createElement('span');
      span.className = 'unit';
      span.dataset.unit = pair + ':' + i;
      span.textContent = text.slice(unit[0], unit[1]);
      node.appendChild(span);
      cursor = unit[1];
    }
    if (cursor < range[1]) {
      node.appendChild(document.createTextNode(text.slice(cursor, range[1])));
    }
    return node;
  }

  function fillColumn(target, spread, side, chapter) {
    if (chapter) target.appendChild(headingNode(chapter, side));
    if (!spread) return;
    eachPart(spread, function (p, from, to, continued) {
      if (side === 'fr') {
        target.appendChild(glossedNode(p, from, to, continued));
        return;
      }
      var node = paragraphNode(p, side, textSpan(englishText(p), from, to), continued);
      // Only the AI column is correctable, so record the slice's offsets and the
      // revert mark only while reading it — never on the published text.
      if (REVISE && S.source === 'translation') markEnNode(node, p, from, to);
      target.appendChild(node);
    });
  }

  function fillMobileColumn(target, spread, chapter) {
    if (chapter) target.appendChild(headingNode(chapter, 'fr'));
    if (!spread) return;
    var first = true;
    eachPart(spread, function (p, from, to, continued) {
      if (!first) target.appendChild(dividerNode());
      var pairBox = mobilePairNode(
        p, from, to, textSpan(englishText(p), from, to), continued
      );
      // The stacked layout is correctable too — record the slice's offsets on its
      // English paragraph, exactly as the two-page layout does.
      if (REVISE && S.source === 'translation') {
        var enNode = pairBox.querySelector('.pair-en');
        if (enNode) markEnNode(enNode, p, from, to);
      }
      target.appendChild(pairBox);
      first = false;
    });
  }

  // Pagination measures the French and the generated English, and nothing else.
  //
  // Measuring the published column too is tempting — it would stop it ever
  // overflowing — but a published translation is aligned to the French by
  // position, so a short French line can be paired with a large block of
  // published prose. Voltaire's "(1752)" is six characters; the published text
  // pairs it with 2,514. Letting that drive the page break leaves the
  // translation view, which is the one being read, about a tenth full.
  // The published column scrolls instead, on the pages where it runs long.
  function measurementColumns() {
    if (S.mobile) {
      return [{ mobile: true, english: function (i) { return generatedEnglish(i); } }];
    }
    return [
      { side: 'fr', text: function (i) { return PAIRS[i].fr; } },
      { side: 'en', text: function (i) { return generatedEnglish(i); } }
    ];
  }

  // ---------- pagination ----------
  // Layout is measured in an offscreen twin of the real book carrying the real
  // classes, so the measured box can never drift from the stylesheet.
  function buildProbe() {
    var host = document.getElementById('measure-host');
    host.textContent = '';
    // Size the probe from the real book's measured box rather than from the
    // stylesheet, so the two can never disagree about how much room a page has.
    var box = view.book.getBoundingClientRect();
    host.style.width = box.width + 'px';
    host.style.height = box.height + 'px';

    var book = document.createElement('div');
    book.className = S.mobile ? 'book-mobile' : 'book-desk';
    book.style.width = '100%';
    book.style.height = '100%';
    book.style.maxHeight = 'none';

    probe.columns = measurementColumns();
    probe.pages = probe.columns.map(function (column) {
      var page = document.createElement('div');
      // Every page has identical geometry, so columns measuring the same side
      // simply overlap each other offscreen.
      page.className = S.mobile
        ? 'page-mobile'
        : 'page page-' + (column.side === 'fr' ? 'left' : 'right');
      book.appendChild(page);
      return page;
    });
    host.appendChild(book);
  }

  function usableHeight(page) {
    var cs = getComputedStyle(page);
    return page.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  }

  function paginateNextSection() {
    if (paginated >= SECTIONS.length) return false;
    var section = SECTIONS[paginated];
    if (!probe.pages || !probe.pages.length) return false;
    var available = usableHeight(probe.pages[0]);
    // Both dimensions matter. A page with height but no width wraps every word
    // onto its own line, which looks like "nothing fits" and puts one paragraph
    // on every spread. Bail and let the layout watcher try again.
    if (available < 40 || probe.pages[0].clientWidth < 80) return false;
    // Leave a few pixels of slack. Heights are integers and the probe is not
    // pixel-identical to the page it stands in for; landing flush against the
    // limit shaves the last line off in the real book.
    var limit = available - fitMargin();

    var inners = probe.pages.map(function (page) {
      page.textContent = '';
      return page.appendChild(document.createElement('div'));
    });

    // Lay a candidate spread out in the probe. This is the only thing that
    // decides where a page ends.
    function fits(from, to, withHeading) {
      var spread = { from: from, to: to };
      for (var c = 0; c < probe.columns.length; c++) {
        var column = probe.columns[c];
        var inner = inners[c];
        inner.textContent = '';
        if (withHeading && section.chapter) {
          inner.appendChild(
            headingNode(section.chapter, column.mobile ? 'fr' : column.side)
          );
        }
        var first = true;
        eachPart(spread, function (p, a, b, continued) {
          if (column.mobile) {
            if (!first) inner.appendChild(dividerNode());
            inner.appendChild(mobilePairNode(
              p, a, b, textSpan(column.english(p), a, b), continued
            ));
          } else {
            inner.appendChild(
              paragraphNode(p, column.side, textSpan(column.text(p), a, b), continued)
            );
          }
          first = false;
        });
        if (inner.offsetHeight > limit) return false;
      }
      return true;
    }

    // How far can a spread starting at `from` reach? Whole paragraphs while
    // they fit, then as much of the next one as the page has room for.
    function spreadEnd(from, withHeading) {
      var whole = null;
      for (var p = from.p; p < section.end; p++) {
        var candidate = position(p + 1, 0);
        if (!fits(from, candidate, withHeading)) break;
        whole = candidate;
      }
      if (whole && whole.p >= section.end) return whole;

      var splitPair = whole ? whole.p : from.p;
      if (splitPair >= section.end) return whole || position(section.end, 0);

      // Binary search the largest fraction of that paragraph that still fits.
      // Both columns are measured at the same fraction, so French and English
      // break at the same point in the paragraph even though the exact word
      // differs, and they line up again where the paragraph ends.
      var low = splitPair === from.p ? from.f : 0;
      var high = 1;
      var best = -1;
      for (var step = 0; step < 12; step++) {
        var mid = (low + high) / 2;
        if (fits(from, position(splitPair, mid), withHeading)) { best = mid; low = mid; }
        else { high = mid; }
      }

      if (best < 0) {
        if (whole) return whole;
        // Nothing fits at all (a pathologically small page): take a bite anyway.
        best = from.f + 0.05;
      }
      // Never end a spread where it began, or pagination cannot move forward.
      if (splitPair === from.p && best <= from.f) best = from.f + 0.05;
      best = Math.min(best, 1);
      return best >= 0.999 ? position(splitPair + 1, 0) : position(splitPair, best);
    }

    var cursor = position(section.start, 0);
    var first = true;
    var guard = 0;
    while (cursor.p < section.end && guard++ < 10000) {
      var end = spreadEnd(cursor, first);
      // End this spread at the reader's position rather than past it, so the
      // next one opens on their line. Fires at most once — the section holding
      // the break — and only inside it, never at the cursor or the natural end.
      if (forcedBreak && posBefore(cursor, forcedBreak) && posBefore(forcedBreak, end)) {
        end = forcedBreak;
      }
      spreads.push({ from: cursor, to: end });
      cursor = end;
      first = false;
    }

    probe.pages.forEach(function (page) { page.textContent = ''; });
    paginated++;
    return true;
  }

  function paginateAll() { while (paginateNextSection()) {} }
  function fullyPaginated() { return paginated >= SECTIONS.length; }

  function ensureThroughPair(pair) {
    while (paginated < SECTIONS.length) {
      var last = spreads[spreads.length - 1];
      if (last && last.to.p > pair) return;
      if (!paginateNextSection()) return;
    }
  }

  function ensureSpreadCount(n) {
    while (spreads.length <= n && paginateNextSection()) {}
  }

  function spreadIndexForPair(pair) {
    for (var i = 0; i < spreads.length; i++) {
      if (spreadCoversPair(spreads[i], pair)) return i;
    }
    return Math.max(0, spreads.length - 1);
  }

  function currentPair() {
    var spread = spreads[S.spreadIndex];
    return spread ? spread.from.p : 0;
  }

  // Where the reader is, as a full position — paragraph and fraction through it.
  // Repagination anchors on this rather than the paragraph alone, so a font or
  // window change keeps your place inside a long paragraph instead of dropping
  // you back at its start.
  function currentPosition() {
    var spread = spreads[S.spreadIndex];
    return spread ? position(spread.from.p, spread.from.f) : position(0, 0);
  }

  // The spread that holds a position: the last one that starts at or before it.
  function spreadIndexForPosition(pos) {
    var index = 0;
    for (var i = 0; i < spreads.length; i++) {
      var from = spreads[i].from;
      if (from.p < pos.p || (from.p === pos.p && from.f <= pos.f + 1e-6)) index = i;
      else break;
    }
    return index;
  }

  // Judge overflow from what is actually on the page, not from what pagination
  // predicted. Pagination measures the translation, so it cannot know that the
  // published column runs longer, that a font substituted, or that a paragraph
  // is simply taller than any page. Whatever the cause, the page scrolls rather
  // than clipping the end of the text.
  function markOverflow(page) {
    page.classList.remove('overflowing');
    if (page.scrollHeight > page.clientHeight + 1) page.classList.add('overflowing');
  }

  function scheduleBackgroundPagination() {
    clearTimeout(backgroundTimer);
    var retries = 0;
    (function step() {
      if (paginateNextSection()) {
        retries = 0;
        if (paginated === 1) paint(); // first section done: show the book
        updateCounter();
        backgroundTimer = setTimeout(step, 0);
        return;
      }
      if (paginated >= SECTIONS.length) {
        updateCounter();
        renderOverlays();
        return;
      }
      // The page box is not measurable yet — a book opened before the browser
      // laid anything out. Wait for it rather than abandoning the rest.
      if (++retries <= LAYOUT_RETRIES) backgroundTimer = setTimeout(step, 120);
    })();
  }

  function repaginate(anchor) {
    spreads = [];
    paginated = 0;
    forcedBreak = anchor;
    buildProbe();
    ensureThroughPair(anchor.p);
    S.spreadIndex = spreadIndexForPosition(anchor);
    paint();
    scheduleBackgroundPagination();
  }

  // ---------- chapters ----------
  function chapterStartingSpread(spreadIndex) {
    var spread = spreads[spreadIndex];
    // Only where the chapter's first paragraph actually begins, not on a spread
    // that merely continues it.
    if (!spread || spread.from.f > 0) return null;
    for (var i = 0; i < SECTIONS.length; i++) {
      if (SECTIONS[i].start === spread.from.p) return SECTIONS[i].chapter;
    }
    return null;
  }

  function chapterForPair(pair) {
    var found = null;
    for (var i = 0; i < CHAPTERS.length; i++) {
      if (CHAPTERS[i].pair <= pair) found = CHAPTERS[i];
    }
    return found;
  }

  // ---------- navigation ----------
  function turning() { return !!S.turn || S.fade; }

  // The URL carries the whole reading state — the page, and the bookmarks with
  // it — so a copied link restores both on another device. "#p<page>", then, if
  // any, "b<page>.<page>…". Written with replaceState so the bar stays current
  // without adding history entries (Back still leaves the book).
  function writeUrl() {
    var hash = '#p' + currentPair();
    if (S.bookmarks.length) hash += 'b' + S.bookmarks.join('.');
    try { history.replaceState(null, '', hash); } catch (e) {}
  }

  function persistPosition() {
    var pos = currentPosition();
    lsSet('last', { v: STORE_VERSION, pair: pos.p, frac: pos.f });
    writeUrl();
    syncSoon();
  }

  // The reading state a link carries, or null if the URL holds none.
  function stateFromHash() {
    var m = /#p(\d+)(?:b([\d.]+))?/.exec(location.hash || '');
    if (!m) return null;
    var valid = function (p) { return typeof p === 'number' && p >= 0 && p < PAIRS.length; };
    var pair = parseInt(m[1], 10);
    var marks = m[2] ? m[2].split('.').map(Number).filter(valid) : [];
    return { pair: valid(pair) ? pair : null, bookmarks: marks };
  }

  function goToSpread(index, animate) {
    if (!S.ready || turning()) return;
    // Nothing may set the spread index to NaN: every later comparison against
    // it is false, so the reader would neither paint nor recover.
    if (typeof index !== 'number' || !isFinite(index)) return;
    ensureSpreadCount(index);
    if (!spreads.length) return;
    var to = Math.max(0, Math.min(spreads.length - 1, index));
    if (to === S.spreadIndex) return;
    if (animate && !reducedMotion && Math.abs(to - S.spreadIndex) === 1) {
      startTurn(to, to > S.spreadIndex ? 'next' : 'prev');
    } else {
      crossFadeTo(to);
    }
  }

  function goToPair(pair, animate) {
    ensureThroughPair(pair);
    goToSpread(spreadIndexForPair(pair), animate);
  }

  // Like goToPair, but honours the fraction through a paragraph, so resuming
  // lands on the page you left rather than the paragraph's first one.
  function goToPosition(pos, animate) {
    ensureThroughPair(pos.p);
    goToSpread(spreadIndexForPosition(pos), animate);
  }

  function step(delta) { goToSpread(S.spreadIndex + delta, Math.abs(delta) === 1); }

  function startTurn(to, direction) {
    S.turn = { dir: direction, from: S.spreadIndex, to: to };
    paint();
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        var leaf = document.getElementById('leaf');
        if (leaf && S.turn) {
          leaf.style.transform =
            S.turn.dir === 'next' ? 'rotateY(-180deg)' : 'rotateY(180deg)';
        }
      });
    });
    clearTimeout(transitionTimer);
    transitionTimer = setTimeout(function () {
      S.spreadIndex = to;
      S.turn = null;
      persistPosition();
      paint();
    }, TURN_MS);
  }

  function crossFadeTo(to) {
    S.fade = true;
    paint();
    clearTimeout(transitionTimer);
    transitionTimer = setTimeout(function () {
      S.spreadIndex = to;
      S.fade = false;
      persistPosition();
      paint();
    }, reducedMotion ? 0 : FADE_MS);
  }

  // ---------- blur reveal ----------
  function setActive(i) {
    if (S.activePair === i || !S.blurEnglish) return;
    var previous = S.activePair;
    S.activePair = i;
    toggleBlurred(previous, true);
    toggleBlurred(i, false);
  }

  function clearActive(i) {
    if (S.activePair !== i) return;
    S.activePair = -1;
    toggleBlurred(i, true);
  }

  function toggleBlurred(pair, blurred) {
    if (pair < 0) return;
    var nodes = document.querySelectorAll('.pair-en[data-pair="' + pair + '"]');
    for (var i = 0; i < nodes.length; i++) nodes[i].classList.toggle('blurred', blurred);
  }

  // ---------- gloss tooltip ----------
  var tip = null;
  var pinned = null;

  function hideTip() {
    if (tip) { tip.remove(); tip = null; }
    if (pinned) { pinned.classList.remove('pinned'); pinned = null; }
  }

  function line(className, text) {
    var el = document.createElement('div');
    el.className = className;
    el.textContent = text;
    return el;
  }

  // A verb-form line: a muted label, then the form itself. The label leads with
  // a middot — the reader's own separator — so "inf · être" reads as a citation,
  // not the prose "from être".
  function formLine(label, value) {
    var el = document.createElement('div');
    el.className = 'tip-form';
    var tag = document.createElement('span');
    tag.className = 'tip-form-label';
    tag.textContent = label + ' · ';
    el.appendChild(tag);
    el.appendChild(document.createTextNode(value));
    return el;
  }

  function showTip(span) {
    hideTip();
    var parts = span.dataset.unit.split(':');
    var unit = (PAIRS[parts[0]].units || [])[Number(parts[1])];
    if (!unit) return;

    tip = document.createElement('div');
    tip.className = 'tip';
    tip.appendChild(line('tip-surface', span.textContent));
    if (unit[2]) tip.appendChild(line('tip-pos', unit[2]));
    tip.appendChild(line('tip-gloss', unit[3]));
    // Only verbs carry these, and only when they say something the surface does not.
    if (unit[4]) tip.appendChild(formLine('inf', unit[4]));
    if (unit[5]) tip.appendChild(formLine('passé composé', unit[5]));
    document.body.appendChild(tip);

    var target = span.getBoundingClientRect();
    var box = tip.getBoundingClientRect();
    var left = target.left + target.width / 2 - box.width / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - box.width - 8));
    // Flip below when there is no room above.
    var above = target.top - box.height - 8;
    tip.style.left = left + 'px';
    tip.style.top = (above >= 8 ? above : target.bottom + 8) + 'px';
  }

  document.getElementById('stage-wrap').addEventListener('mouseover', function (e) {
    var span = e.target.closest && e.target.closest('.unit');
    if (span && !pinned) showTip(span);
  });
  document.getElementById('stage-wrap').addEventListener('mouseout', function (e) {
    var span = e.target.closest && e.target.closest('.unit');
    if (span && !pinned) hideTip();
  });
  // Touch has no hover: a tap pins the tooltip, and the click that would have
  // turned the page is swallowed.
  document.getElementById('stage-wrap').addEventListener('click', function (e) {
    var span = e.target.closest && e.target.closest('.unit');
    if (!span) return;
    e.stopPropagation();
    if (pinned === span) { hideTip(); return; }
    hideTip();
    showTip(span);
    pinned = span;
    span.classList.add('pinned');
  }, true);

  // ---------- glossing on demand ----------
  // A second implementation of biread/gloss.py's judgement, because the reader
  // is who pays for it and the reader is not Python. The algorithms are written
  // twice; the French they read is written once and travels in GLOSS, so the two
  // cannot quietly disagree about the language. tests/test_gloss_parity.py holds
  // them to the same answers on the same paragraphs.
  //
  // The safety argument is the one gloss.py makes: what comes back is a
  // *proposal*. Every unit is located in the real paragraph and only its offsets
  // are kept, so a model that fixes an accent or drops a word cannot put its
  // version on the page — at worst the search fails and the paragraph stays
  // plain.
  var WORD_RE = /[\p{L}\p{M}]+/gu;
  var NON_WORD_RE = /[^\p{L}\p{N}_]+/gu;

  function wordsIn(text) { return text.toLowerCase().match(WORD_RE) || []; }
  function inList(list, word) { return list.indexOf(word) !== -1; }

  // Normalised text, and a map from each normalised index back to the original.
  // Models normalise typography however firmly they are told not to, and French
  // prose is one long chain of elisions, so matching is done on the folded form
  // while offsets keep pointing at the source character for character.
  function foldText(text) {
    var out = '', index = [], i, j, folded;
    for (i = 0; i < text.length; i++) {
      folded = GLOSS.fold[text[i]] || text[i];
      for (j = 0; j < folded.length; j++) { out += folded[j]; index.push(i); }
    }
    return { text: out, index: index };
  }

  function sameForm(a, b) {
    return !!a && a.replace(NON_WORD_RE, '').toLowerCase()
      === b.replace(NON_WORD_RE, '').toLowerCase();
  }

  // A compound past is a present auxiliary plus a participle. Anything offered
  // as a passé composé without one is some other tense wearing its name, and a
  // false grammatical claim is worse than none.
  function isPerfect(form) {
    if (!GLOSS.perfectAuxiliaries.length) return true;
    var words = wordsIn(form);
    for (var i = 0; i < words.length; i++) {
      if (inList(GLOSS.perfectAuxiliaries, words[i])) return true;
    }
    return false;
  }

  function parseUnits(block) {
    var lines = block.split('\n'), units = [], i, k, parts, unit, extra, eq;
    for (i = 0; i < lines.length; i++) {
      parts = lines[i].split(GLOSS.field).map(function (p) { return p.trim(); });
      if (parts.length < 3 || !parts[0]) continue;
      unit = { surface: parts[0], pos: parts[1], gloss: parts[2], infinitive: '', perfect: '' };
      for (k = 3; k < parts.length; k++) {
        extra = parts[k];
        eq = extra.indexOf('=');
        if (eq === -1) continue;
        if (extra.slice(0, eq).trim() === 'inf') unit.infinitive = extra.slice(eq + 1).trim();
        else if (extra.slice(0, eq).trim() === 'pc') unit.perfect = extra.slice(eq + 1).trim();
      }
      if (sameForm(unit.perfect, unit.surface) || !isPerfect(unit.perfect)) unit.perfect = '';
      units.push(unit);
    }
    return units;
  }

  // Locate each proposed unit, in order. Null if any one cannot be found at or
  // after the last — the model has lost its place, and the whole segmentation is
  // untrustworthy. Gaps are fine; they render as plain text.
  function anchorUnits(paragraph, proposed) {
    var hay = foldText(paragraph), located = [], cursor = 0, i, surface, found;
    for (i = 0; i < proposed.length; i++) {
      surface = foldText(proposed[i].surface).text.trim();
      if (!surface) continue;
      found = hay.text.indexOf(surface, cursor);
      if (found === -1) return null;
      cursor = found + surface.length;
      located.push([
        hay.index[found], hay.index[found + surface.length - 1] + 1,
        proposed[i].pos, proposed[i].gloss, proposed[i].infinitive, proposed[i].perfect
      ]);
    }
    return located.length ? located : null;
  }

  // True if a marker word sits between two content words: "Moscovie ou Chine"
  // and "citoyens de la terre" are each two logical parts, and a hover explains
  // one part. A leading "et …" is not — nothing content-bearing precedes it.
  function splitBetweenContent(surface, markers) {
    var words = wordsIn(surface), seen = false, pending = false, i;
    for (i = 0; i < words.length; i++) {
      if (inList(markers, words[i]) && seen) pending = true;
      else if (!inList(GLOSS.functionWords, words[i])) {
        if (pending) return true;
        seen = true;
      }
    }
    return false;
  }

  function contentWords(surface) {
    return wordsIn(surface).filter(function (w) {
      return !inList(GLOSS.functionWords, w);
    });
  }

  // Too wide to be one hover. A noun phrase may carry an adjective, so two
  // content words are allowed; anything that predicates may not, because its
  // second content word is a subject or an object rather than part of the phrase.
  function overBroad(surface, pos) {
    if (splitBetweenContent(surface, GLOSS.coordinators)) return true;
    if (splitBetweenContent(surface, GLOSS.prepositions)) return true;
    var limit = new RegExp(GLOSS.predicatePos, 'i').test(pos || '')
      ? 1 : GLOSS.maxContentWords;
    return contentWords(surface).length > limit;
  }

  // The width rule applied at the edge where units become hovers, so tightening
  // it drops the offenders on the next render with nothing to pay again.
  function displayableUnits(paragraph, units) {
    var shown = [], i, u, surface;
    for (i = 0; i < units.length; i++) {
      u = units[i];
      surface = paragraph.slice(u[0], u[1]);
      if (overBroad(surface, u[2])) continue;
      if (u[5] && (sameForm(u[5], surface) || !isPerfect(u[5]))) {
        shown.push([u[0], u[1], u[2], u[3], u[4], '']);
      } else shown.push(u);
    }
    return shown;
  }

  // Glosses a reader has bought, kept against the source paragraph so they
  // survive a rebuild and go stale safely if that paragraph changes — the same
  // bargain a correction makes.
  function loadBoughtGlosses() {
    var stored = lsGet('glosses');
    bought = stored && stored.byHash ? stored.byHash : {};
    for (var i = 0; i < PAIRS.length; i++) {
      if (!PAIRS[i].units && PAIRS[i].h && bought[PAIRS[i].h]) {
        PAIRS[i].units = displayableUnits(PAIRS[i].fr, bought[PAIRS[i].h]);
      }
    }
  }

  // Paragraphs on the French page in front of the reader that have no units yet.
  // The published column is somebody else's prose and is never glossed; the
  // French is what carries the hover.
  function unglossedHere() {
    var spread = spreads[S.spreadIndex], want = [];
    if (!spread) return want;
    eachPart(spread, function (p) {
      if (!PAIRS[p].units && PAIRS[p].fr.trim() && want.indexOf(p) === -1) want.push(p);
    });
    return want;
  }

  function updateGlossButton() {
    var btn = document.getElementById('gloss-btn');
    if (!btn) return;
    // Shown only where there is something to gloss and somewhere to ask. A page
    // already glossed offers nothing, which is the honest state of that page.
    var pending = GLOSS && !S.mobile && GLOSS.endpoint ? unglossedHere() : [];
    btn.hidden = !pending.length;
    btn.disabled = glossBusy;
    btn.textContent = i18n(glossBusy ? 'glossAdding' : 'glossAdd');
  }

  // One call for the page: five short paragraphs cost a fifth of five calls, and
  // the model reads them as the continuous prose they are.
  function glossPrompt(indices) {
    var lines = [];
    for (var i = 0; i < indices.length; i++) {
      lines.push('@@@' + (i + 1) + '@@@\n' + PAIRS[indices[i]].fr);
    }
    return lines.join('\n\n');
  }

  function glossPage() {
    if (!GLOSS || glossBusy) return;
    var indices = unglossedHere();
    if (!indices.length) return;
    if (!apiKey) { openKeyPanel(GLOSS, glossPage); return; }
    glossBusy = true;
    updateGlossButton();
    // Output runs several times the input here, so the ceiling is generous.
    providerRequest(GLOSS, apiKey, GLOSS.prompt, glossPrompt(indices), 8192).then(
      function (out) {
        glossBusy = false;
        var landed = applyGlosses(indices, out);
        // Settle the button before saying anything on it: updateGlossButton
        // rewrites the label, so reporting first would erase the report.
        updateGlossButton();
        if (!landed) showGlossError();
      },
      function () { glossBusy = false; updateGlossButton(); showGlossError(); }  // same order
    );
  }

  // Split the reply on its paragraph markers and locate each block in the
  // paragraph it claims to be about. A block that will not anchor leaves that
  // paragraph plain — never a guess, and never the model's own text on the page.
  function applyGlosses(indices, reply) {
    var blocks = String(reply || '').split(/@@@\s*(\d+)\s*@@@/), any = false, i;
    var byNumber = {};
    for (i = 1; i < blocks.length; i += 2) byNumber[Number(blocks[i])] = blocks[i + 1] || '';
    for (i = 0; i < indices.length; i++) {
      var block = byNumber[i + 1];
      // One paragraph asked for and no marker returned: the whole reply is that
      // paragraph's answer.
      if (block == null && indices.length === 1 && blocks.length === 1) block = blocks[0];
      if (!block) continue;
      var located = anchorUnits(PAIRS[indices[i]].fr, parseUnits(block));
      if (!located) continue;
      PAIRS[indices[i]].units = displayableUnits(PAIRS[indices[i]].fr, located);
      if (PAIRS[indices[i]].h) bought[PAIRS[indices[i]].h] = located;
      any = true;
    }
    if (!any) return false;
    lsSet('glosses', { v: STORE_VERSION, byHash: bought });
    paint();
    return true;
  }

  function showGlossError() {
    var btn = document.getElementById('gloss-btn');
    if (!btn) return;
    btn.textContent = i18n('glossFailed');
    setTimeout(updateGlossButton, 3200);
  }

  // ---------- revise ----------
  // Correct the AI translation in place: select a phrase, then rewrite it on the
  // reader's OWN key or type the fix by hand. A fix is a local override (above);
  // nothing here runs, and no key field appears, unless the build passed --revise.
  var PROVIDER_LABEL = {
    anthropic: 'Anthropic', openai: 'OpenAI', openrouter: 'OpenRouter', ollama: 'Ollama'
  };
  function providerLabel(cfg) {
    var of = cfg || REVISE || GLOSS;
    return of ? (PROVIDER_LABEL[of.provider] || of.provider) : '';
  }
  function reviseText(key, cfg) { return i18n(key).replace('{provider}', providerLabel(cfg)); }

  // Record the visible slice's offsets into the full generated text (so a
  // selection maps back to the whole paragraph), and, on a corrected paragraph,
  // a revert mark. The mark is absolutely positioned, so it never affects the
  // measured height. Called only in the live paint — the probe never sees it.
  function markEnNode(node, i, from, to) {
    var range = spanRange(generatedEnglish(i), from, to);
    node.dataset.enFrom = range[0];
    node.dataset.enTo = range[1];
    if (!hasOverride(i)) return;
    node.classList.add('revised');
    var undo = document.createElement('button');
    undo.type = 'button';
    undo.className = 'revise-undo';
    undo.textContent = '↺';
    undo.title = i18n('reviseUndo');
    undo.setAttribute('aria-label', i18n('reviseUndo'));
    undo.addEventListener('click', function (e) { e.stopPropagation(); revertRevision(i); });
    node.appendChild(undo);
  }

  function closestEn(target) {
    var el = target.nodeType === 1 ? target : target.parentElement;
    return el && el.closest ? el.closest('.pair-en') : null;
  }

  function onEnSelection() {
    if (!REVISE || reviseBusy) return;
    if (S.source !== 'translation' || S.blurEnglish) return;
    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    var text = sel.toString();
    if (!text.trim()) return;
    var range = sel.getRangeAt(0);
    var stage = document.getElementById('stage-wrap');
    if (!stage.contains(range.commonAncestorContainer)) return;
    var node = closestEn(range.commonAncestorContainer);
    if (!node || node.dataset.enFrom == null) return;
    if (!node.contains(range.startContainer) || !node.contains(range.endContainer)) return;
    var pre = document.createRange();
    pre.selectNodeContents(node);
    try { pre.setEnd(range.startContainer, range.startOffset); }
    catch (e) { return; }
    var start = Number(node.dataset.enFrom) + pre.toString().length;
    showReviseControl(Number(node.dataset.pair), start, start + text.length,
      range.getBoundingClientRect());
  }

  function reviseButton(key, fn, primary) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'revise-btn' + (primary ? ' primary' : '');
    b.textContent = i18n(key);
    b.addEventListener('click', fn);
    return b;
  }

  function showReviseControl(i, start, end, rect) {
    hideRevise();
    reviseTarget = { i: i, start: start, end: end };
    var ctl = document.createElement('div');
    ctl.className = 'revise';
    ctl.addEventListener('mousedown', function (e) { e.stopPropagation(); });
    ctl.addEventListener('click', function (e) { e.stopPropagation(); });

    var note = document.createElement('input');
    note.type = 'text';
    note.className = 'revise-note';
    note.placeholder = i18n('reviseNotePlaceholder');
    note.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Enter') runRewrite();
      else if (e.key === 'Escape') hideRevise();
    });
    ctl.appendChild(note);
    ctl._note = note;

    var row = document.createElement('div');
    row.className = 'revise-row';
    row.appendChild(reviseButton('reviseEdit', onEditPressed));
    row.appendChild(reviseButton('reviseRegenerate', runRewrite, true));
    ctl.appendChild(row);

    var foot = document.createElement('div');
    foot.className = 'revise-foot';
    var keyBtn = document.createElement('button');
    keyBtn.type = 'button';
    keyBtn.className = 'revise-link';
    keyBtn.textContent = i18n('reviseKeyManage');
    keyBtn.addEventListener('click', openKeyPanel);
    foot.appendChild(keyBtn);
    if (hasOverride(i)) {
      var undo = document.createElement('button');
      undo.type = 'button';
      undo.className = 'revise-link';
      undo.textContent = i18n('reviseUndo');
      undo.addEventListener('click', function () { revertRevision(i); });
      foot.appendChild(undo);
    }
    ctl.appendChild(foot);

    document.body.appendChild(ctl);
    reviseCtl = ctl;
    positionBy(ctl, rect);
  }

  // Edit: if the reader typed a replacement straight into the field, that IS the
  // fix — apply it at once, no editor step. An empty field opens the inline editor
  // on the current span instead.
  function onEditPressed() {
    if (!reviseTarget) return;
    var typed = reviseCtl && reviseCtl._note ? reviseCtl._note.value.trim() : '';
    if (typed) applyRevision(reviseTarget.i, reviseTarget.start, reviseTarget.end, typed);
    else startManualEdit();
  }

  // Manual edit: turn the span into an editable field, no key and no call. This
  // is your example's shortest path — a reader who knows the fix just types it.
  function startManualEdit() {
    if (!reviseTarget) return;
    var current = generatedEnglish(reviseTarget.i).slice(reviseTarget.start, reviseTarget.end);
    reviseCtl.textContent = '';
    var input = document.createElement('textarea');
    input.className = 'revise-edit';
    input.rows = 2;
    input.value = current;
    input.addEventListener('mousedown', function (e) { e.stopPropagation(); });
    input.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); saveManualEdit(input.value); }
      else if (e.key === 'Escape') hideRevise();
    });
    reviseCtl.appendChild(input);
    var row = document.createElement('div');
    row.className = 'revise-row';
    row.appendChild(reviseButton('reviseCancel', hideRevise));
    row.appendChild(reviseButton('reviseSave', function () { saveManualEdit(input.value); }, true));
    reviseCtl.appendChild(row);
    input.focus();
    input.select();
  }
  function saveManualEdit(value) {
    if (reviseTarget) applyRevision(reviseTarget.i, reviseTarget.start, reviseTarget.end, value.trim());
  }

  function runRewrite() {
    if (!reviseTarget || reviseBusy) return;
    if (!apiKey) { openKeyPanel(REVISE, runRewrite); return; } // offsets live in reviseTarget, not the DOM selection
    var i = reviseTarget.i, start = reviseTarget.start, end = reviseTarget.end;
    var note = reviseCtl && reviseCtl._note ? reviseCtl._note.value.trim() : '';
    var full = generatedEnglish(i);
    var prompts = revisePrompts(PAIRS[i].fr, full, full.slice(start, end), note);
    setReviseBusy(true);
    providerRequest(REVISE, apiKey, prompts.system, prompts.user).then(function (out) {
      setReviseBusy(false);
      var revised = cleanSpan(out);
      if (revised) applyRevision(i, start, end, revised);
      else showReviseError();
    }, function () {
      setReviseBusy(false);
      showReviseError();
    });
  }

  function cleanSpan(text) {
    var t = (text || '').trim();
    if (t.length > 1 && /^["'“‘]/.test(t) && /["'”’]$/.test(t)) {
      t = t.slice(1, -1).trim();
    }
    return t;
  }

  function applyRevision(i, start, end, revised) {
    if (!revised || !PAIRS[i].h) return;
    var h = PAIRS[i].h, full = generatedEnglish(i);
    undoStack.push({ h: h, prev: overrides[h] || null }); // remember the pre-edit state
    overrides[h] = { base: PAIRS[i].en, text: full.slice(0, start) + revised + full.slice(end),
                     at: Date.now() };
    saveOverrides();
    updateEditsButton();
    hideRevise();
    syncSoon();
    repaginate(currentPosition());
  }
  function revertRevision(i) {
    if (PAIRS[i].h) { delete overrides[PAIRS[i].h]; saveOverrides(); syncSoon(); }
    updateEditsButton();
    hideRevise();
    repaginate(currentPosition());
  }
  // Step back through this session's corrections — one paragraph's history at a
  // time, restoring whatever it was before that edit (an earlier fix, or nothing).
  function undoLastEdit() {
    if (!undoStack.length) return false;
    var entry = undoStack.pop();
    if (entry.prev) overrides[entry.h] = entry.prev;
    else delete overrides[entry.h];
    saveOverrides();
    updateEditsButton();
    hideRevise();
    repaginate(currentPosition());
    return true;
  }

  function setReviseBusy(busy) {
    reviseBusy = busy;
    if (!reviseCtl) return;
    var fields = reviseCtl.querySelectorAll('button, input, textarea');
    for (var i = 0; i < fields.length; i++) fields[i].disabled = busy;
    reviseStatus(busy ? i18n('reviseWorking') : '', false);
  }
  function showReviseError() { reviseStatus(i18n('reviseError'), true); }
  function reviseStatus(text, isError) {
    if (!reviseCtl) return;
    var status = reviseCtl.querySelector('.revise-status');
    if (!text) { if (status) status.remove(); return; }
    if (!status) {
      status = document.createElement('div');
      status.className = 'revise-status';
      reviseCtl.appendChild(status);
    }
    status.classList.toggle('error', !!isError);
    status.textContent = text;
  }

  function hideRevise() {
    if (reviseCtl) { reviseCtl.remove(); reviseCtl = null; }
    reviseTarget = null;
    reviseBusy = false;
  }

  function positionBy(el, rect) {
    var box = el.getBoundingClientRect();
    var left = rect.left + rect.width / 2 - box.width / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - box.width - 8));
    var above = rect.top - box.height - 8;
    el.style.left = left + 'px';
    el.style.top = (above >= 8 ? above : rect.bottom + 8) + 'px';
  }

  // The key-entry panel reuses the ⓘ panel's look. The key is sent only to the
  // provider's own endpoint (providerRequest) and, when remembered, kept only in
  // this browser. No token, price, or spend figure appears anywhere.
  // Shared by correction and glossing: same key, same provider, different
  // reason for wanting it. `after` is what the key was asked for.
  function openKeyPanel(cfg, after) {
    cfg = cfg || REVISE;
    closeKeyPanel();
    if (reviseCtl) reviseCtl.hidden = true; // one panel at a time — keep it light
    var panel = document.createElement('div');
    panel.className = 'info-panel revise-key' + (S.mobile ? ' mobile' : '');
    panel.addEventListener('mousedown', function (e) { e.stopPropagation(); });
    panel.addEventListener('click', function (e) { e.stopPropagation(); });

    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'info-close';
    close.textContent = '×';
    close.setAttribute('aria-label', i18n('close'));
    close.addEventListener('click', closeKeyPanel);
    panel.appendChild(close);

    var title = document.createElement('div');
    title.className = 'info-title';
    title.textContent = i18n(cfg === GLOSS ? 'glossKeyTitle' : 'reviseKeyTitle');
    var rule = document.createElement('div');
    rule.className = 'info-rule';
    var body = document.createElement('div');
    body.className = 'info-body';
    body.textContent = reviseText('reviseKeyBody', cfg);
    panel.appendChild(title);
    panel.appendChild(rule);
    panel.appendChild(body);

    var input = document.createElement('input');
    input.type = 'password';
    input.className = 'revise-key-input';
    input.autocomplete = 'off';
    input.placeholder = reviseText('reviseKeyPlaceholder', cfg);
    input.value = apiKey;
    input.addEventListener('mousedown', function (e) { e.stopPropagation(); });
    input.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Enter') commit();
    });
    panel.appendChild(input);

    var remember = document.createElement('label');
    remember.className = 'revise-remember';
    var cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.checked = true;
    remember.appendChild(cb);
    remember.appendChild(document.createTextNode(' ' + i18n('reviseRemember')));
    panel.appendChild(remember);

    var row = document.createElement('div');
    row.className = 'revise-row';
    var forget = reviseButton('reviseForget', function () {
      apiKey = '';
      storeKey('', false, cfg);
      input.value = '';
      input.focus();
    });
    var save = reviseButton('reviseSave', commit, true);
    row.appendChild(forget);
    row.appendChild(save);
    panel.appendChild(row);

    function commit() {
      apiKey = input.value.trim();
      storeKey(apiKey, cb.checked, cfg);
      closeKeyPanel();
      if (!apiKey) return;
      if (after) after();
      else if (reviseTarget) runRewrite();
    }

    document.body.appendChild(panel);
    keyPanel = panel;
    input.focus();
  }
  function closeKeyPanel() {
    if (keyPanel) { keyPanel.remove(); keyPanel = null; }
    if (reviseCtl) reviseCtl.hidden = false;
  }

  // One browser-side client, shaped by the wire style the build recorded, and
  // pointed at whichever feature is calling — correcting a phrase or glossing a
  // paragraph. An endpoint is embedded only by --revise or gloss-on-demand, so a
  // plain book carries no URL at all; the key rides only on the request to that
  // endpoint, and nowhere else.
  function providerRequest(cfg, key, system, user, maxTokens) {
    var style = cfg.style, url = cfg.endpoint, headers, body;
    if (!url) return Promise.reject(new Error('no endpoint'));
    if (style === 'anthropic') {
      headers = {
        'content-type': 'application/json', 'x-api-key': key,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true'
      };
      body = {
        model: cfg.model, max_tokens: maxTokens || 1024, system: system,
        messages: [{ role: 'user', content: user }]
      };
    } else {
      // OpenAI-compatible (openai, openrouter) and Ollama share a messages shape;
      // only the auth header and the local streaming flag differ.
      headers = { 'content-type': 'application/json' };
      if (style !== 'ollama') headers.authorization = 'Bearer ' + key;
      body = {
        model: cfg.model,
        messages: [{ role: 'system', content: system }, { role: 'user', content: user }]
      };
      if (style === 'ollama') body.stream = false;
    }
    return fetch(url, { method: 'POST', headers: headers, body: JSON.stringify(body) })
      .then(readResponse(style));
  }

  function readResponse(kind) {
    return function (res) {
      if (!res.ok) throw new Error('http ' + res.status);
      return res.json().then(function (data) {
        if (kind === 'anthropic') {
          return (data.content || []).filter(function (b) { return b.type === 'text'; })
            .map(function (b) { return b.text; }).join('');
        }
        if (kind === 'ollama') return (data.message && data.message.content) || '';
        return (data.choices && data.choices[0] && data.choices[0].message
          && data.choices[0].message.content) || '';
      });
    };
  }

  // A targeted-edit prompt: the model rewrites ONLY the selected span, with the
  // French source as the ground truth and the whole translation as context.
  function revisePrompts(paragraphFr, paragraphEn, span, note) {
    var target = (REVISE && REVISE.target) || 'English';
    var system = 'You are refining one short span inside an existing ' + target +
      ' literary translation of a French text. You are given the French source, the ' +
      'current ' + target + ' translation, and one selected span of that translation to ' +
      'rewrite. Return ONLY the rewritten span — the exact replacement text, with no ' +
      'quotation marks, no explanation, and no surrounding words. Keep the same register ' +
      'and tense; change only what is needed so the span reads as natural, idiomatic ' +
      target + ' faithful to the French. If the reader says what is wrong, honor it.';
    var user = 'French source:\n' + paragraphFr +
      '\n\nCurrent ' + target + ' translation:\n' + paragraphEn +
      '\n\nSelected span to rewrite:\n' + span +
      (note ? '\n\nWhat is wrong: ' + note : '') +
      '\n\nReturn only the rewritten span.';
    return { system: system, user: user };
  }

  // ---- carry corrections between browsers, as a link ----
  // A separate link from "copy link to this page" on purpose: the page link is
  // for sharing where you are, so a reader's private edits must never ride it.
  // This one carries the corrections in its own #e= fragment and loads them when
  // the link is opened. A file:// link reaches only other browsers on the same
  // machine (a path is not portable across devices); a hosted book's link travels
  // anywhere. base64 is URL-safed; a heavily-edited book makes a long link.
  function encodeEdits(obj) {
    var b64 = btoa(unescape(encodeURIComponent(JSON.stringify(obj))));
    return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  function decodeEdits(s) {
    var b64 = s.replace(/-/g, '+').replace(/_/g, '/');
    while (b64.length % 4) b64 += '=';
    return JSON.parse(decodeURIComponent(escape(atob(b64))));
  }
  function buildEditsLink() {
    return location.href.split('#')[0] + '#e=' + encodeEdits(overrides);
  }
  function importEditsFromHash() {
    var m = /[#&]e=([A-Za-z0-9\-_]+)/.exec(location.hash || '');
    if (m) {
      try {
        var incoming = decodeEdits(m[1]);
        for (var k in incoming) {
          if (incoming[k] && typeof incoming[k].text === 'string'
              && typeof incoming[k].base === 'string') overrides[k] = incoming[k];
        }
        saveOverrides();
      } catch (e) {}
      // Drop the payload from the URL so it is neither re-imported nor re-shared.
      try { history.replaceState(null, '', location.pathname + location.search); } catch (e) {}
    }
  }
  function updateEditsButton() {
    var btn = document.getElementById('edits-btn');
    if (!btn) return;
    var has = false;
    for (var k in overrides) { if (overrides[k]) { has = true; break; } }
    btn.hidden = !has;
  }

  if (REVISE) {
    // Read the selection after the browser has settled it.
    document.getElementById('stage-wrap').addEventListener('mouseup', function () {
      setTimeout(onEnSelection, 0);
    });
    // A press outside the control (or panel) dismisses it — but not mid-request,
    // and the key panel counts as part of the control, so using it never drops
    // the pending selection the rewrite still needs.
    document.addEventListener('mousedown', function (e) {
      if (reviseBusy) return;
      var inside = e.target.closest && e.target.closest('.revise, .revise-key');
      if (reviseCtl && !inside) hideRevise();
      if (keyPanel && !inside) closeKeyPanel();
    }, true);

    // Cmd/Ctrl+Z undoes the last correction — but leaves native undo to the field
    // or key input while the reader is typing in one.
    document.addEventListener('keydown', function (e) {
      if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.altKey) return;
      if (e.key !== 'z' && e.key !== 'Z') return;
      var t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return;
      if (undoLastEdit()) e.preventDefault();
    });

    // Copy the reader's corrections as their own link (see above).
    var editsBtn = document.getElementById('edits-btn');
    if (editsBtn) {
      var editsFlash = null;
      editsBtn.addEventListener('click', function () {
        var url = buildEditsLink();
        var done = function () {
          editsBtn.classList.add('copied');
          clearTimeout(editsFlash);
          editsFlash = setTimeout(function () { editsBtn.classList.remove('copied'); }, 1600);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(url).then(done, function () { prompt('Copy your edits link:', url); });
        } else {
          prompt('Copy your edits link:', url);
        }
      });
    }
  }

  // ---------- mounting ----------
  function mount() {
    var wrap = document.getElementById('stage-wrap');
    wrap.className = S.mobile ? 'mobile' : '';
    wrap.textContent = '';

    var book = document.createElement('div');
    book.className = S.mobile ? 'book-mobile' : 'book-desk';
    book.addEventListener('click', onBookClick);
    book.addEventListener('mousedown', onBookPress, { passive: true });
    book.addEventListener('touchstart', onTouchStart, { passive: true });
    book.addEventListener('touchend', onTouchEnd, { passive: true });

    view = { book: book };
    if (S.mobile) {
      view.page = document.createElement('div');
      view.page.className = 'page-mobile';
      book.appendChild(view.page);
    } else {
      view.left = document.createElement('div');
      view.left.className = 'page page-left';
      view.right = document.createElement('div');
      view.right.className = 'page page-right';
      var gutter = document.createElement('div');
      gutter.className = 'gutter';
      book.appendChild(view.left);
      book.appendChild(view.right);
      book.appendChild(gutter);
    }

    view.ribbonHost = document.createElement('div');
    book.appendChild(view.ribbonHost);
    wrap.appendChild(book);
  }


  // ---------- painting ----------
  function paint(options) {
    if (!S.ready) return;
    hideTip(); // the span it was anchored to is about to be replaced
    if (REVISE) hideRevise(); // the selection it was anchored to is about to be replaced
    updateCounter();
    updateBookmarkStar();
    view.book.style.opacity = S.fade ? '0' : '1';
    if (S.mobile) paintMobile(options); else paintDesk(options);
    paintRibbon();
    if (GLOSS) updateGlossButton();
  }

  function pageInner(xfade) {
    var inner = document.createElement('div');
    if (xfade) inner.className = 'xfade';
    return inner;
  }

  function pageNumber(index, mobile, side) {
    var num = document.createElement('div');
    num.className = mobile ? 'page-num-mobile' : 'page-num page-num-' + side;
    num.textContent = String(index + 1);
    // The translated side's folio hides with its column while blur is on, like
    // its language tag — nothing on the right gives the hidden page away.
    if (side === 'right' && S.blurEnglish) num.classList.add('blurred');
    return num;
  }

  // A discreet running head naming the page's language: FR on the French left,
  // the target code on the translated right. Desktop only — the stacked mobile
  // column interleaves both languages, so a single side tag would not fit it.
  function cornerTag(lang) {
    var isSource = lang === 'fr';
    var tag = document.createElement('div');
    tag.className = 'page-corner page-corner-' + (isSource ? 'left' : 'right');
    tag.textContent = isSource ? SOURCE_TAG : TARGET_TAG;
    // The translation-side tag hides with its column while blur is on.
    if (!isSource && S.blurEnglish) tag.classList.add('blurred');
    return tag;
  }

  function paintDesk(options) {
    var t = S.turn;
    var leftIndex = t ? (t.dir === 'next' ? t.from : t.to) : S.spreadIndex;
    var rightIndex = t ? (t.dir === 'next' ? t.to : t.from) : S.spreadIndex;

    view.left.textContent = '';
    var leftInner = pageInner(false);
    fillColumn(leftInner, spreads[leftIndex], 'fr', chapterStartingSpread(leftIndex));
    view.left.appendChild(leftInner);
    view.left.appendChild(cornerTag('fr'));
    view.left.appendChild(pageNumber(leftIndex, false, 'left'));
    markOverflow(view.left);

    view.right.textContent = '';
    var rightInner = pageInner(options && options.xfade);
    fillColumn(rightInner, spreads[rightIndex], 'en', chapterStartingSpread(rightIndex));
    view.right.appendChild(rightInner);
    view.right.appendChild(cornerTag('en'));
    view.right.appendChild(pageNumber(rightIndex, false, 'right'));
    markOverflow(view.right);

    var existing = document.getElementById('leaf');
    if (existing) existing.remove();
    if (t) view.book.appendChild(buildLeaf(t));
  }

  function paintMobile(options) {
    var index = S.turn ? S.turn.to : S.spreadIndex;
    view.page.textContent = '';
    var inner = pageInner(options && options.xfade);
    fillMobileColumn(inner, spreads[index], chapterStartingSpread(index));
    view.page.appendChild(inner);
    view.page.appendChild(pageNumber(index, true));
    markOverflow(view.page);

    var existing = document.getElementById('leaf');
    if (existing) existing.remove();
    if (S.turn) view.book.appendChild(buildMobileLeaf(S.turn));
  }

  function leafShade(direction) {
    var angle = direction === 'next' ? '100deg' : '260deg';
    var shade = document.createElement('div');
    shade.className = 'leaf-shade';
    shade.style.background =
      'linear-gradient(' + angle + ', rgba(0,0,0,.24) 0%, rgba(0,0,0,.06) 26%, ' +
      'rgba(255,255,255,.12) 46%, rgba(0,0,0,.05) 70%, rgba(0,0,0,.22) 100%)';
    return shade;
  }

  function buildLeaf(t) {
    var fromRight = t.dir === 'prev';
    var face = t.dir === 'next' ? 'right' : 'left';
    var frontLang = t.dir === 'next' ? 'en' : 'fr';
    var backLang = t.dir === 'next' ? 'fr' : 'en';

    var leaf = document.createElement('div');
    leaf.className = 'leaf';
    leaf.id = 'leaf';
    leaf.style.left = fromRight ? '0' : '50%';
    leaf.style.transformOrigin = fromRight ? 'right center' : 'left center';
    leaf.style.transform = 'rotateY(0deg)';

    function buildFace(index, lang, flipped) {
      var page = document.createElement('div');
      page.className = 'page page-' + face + ' leaf-face';
      page.style.left = '0';
      page.style.right = '0';
      page.style.width = '100%';
      if (flipped) page.style.transform = 'rotateY(180deg)';
      var inner = pageInner(false);
      fillColumn(inner, spreads[index], lang, chapterStartingSpread(index));
      page.appendChild(inner);
      page.appendChild(cornerTag(lang));
      page.appendChild(pageNumber(index, false, lang === 'fr' ? 'left' : 'right'));
      return page;
    }

    leaf.appendChild(buildFace(t.from, frontLang, false));
    leaf.appendChild(buildFace(t.to, backLang, true));
    leaf.appendChild(leafShade(t.dir));
    return leaf;
  }

  function buildMobileLeaf(t) {
    var leaf = document.createElement('div');
    leaf.className = 'leaf-mobile';
    leaf.id = 'leaf';
    leaf.style.transformOrigin = t.dir === 'prev' ? 'right center' : 'left center';
    leaf.style.transform = 'rotateY(0deg)';

    function buildFace(index, flipped) {
      var page = document.createElement('div');
      page.className = 'page-mobile leaf-face';
      if (flipped) page.style.transform = 'rotateY(180deg)';
      var inner = pageInner(false);
      fillMobileColumn(inner, spreads[index], chapterStartingSpread(index));
      page.appendChild(inner);
      page.appendChild(pageNumber(index, true));
      return page;
    }

    leaf.appendChild(buildFace(t.from, false));
    leaf.appendChild(buildFace(t.to, true));
    leaf.appendChild(leafShade(t.dir));
    return leaf;
  }

  function paintRibbon() {
    view.ribbonHost.textContent = '';
    if (bookmarkOnSpread(S.spreadIndex) < 0) return;
    var ribbon = document.createElement('div');
    ribbon.className = 'ribbon';
    ribbon.style.left = S.mobile ? '50%' : 'calc(50% + 60px)';
    ribbon.style.transform = 'translateX(-50%)';
    ribbon.setAttribute('role', 'button');
    ribbon.setAttribute('tabindex', '0');
    ribbon.setAttribute('aria-label', i18n('removeBookmark'));
    ribbon.addEventListener('click', function (e) { e.stopPropagation(); toggleBookmark(); });
    ribbon.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); toggleBookmark(); }
    });
    var inner = document.createElement('div');
    inner.className = 'ribbon-inner';
    ribbon.appendChild(inner);
    view.ribbonHost.appendChild(ribbon);
  }


  function updateCounter() {
    var el = document.getElementById('counter');
    if (!S.ready || !spreads.length) { el.textContent = ''; return; }
    el.textContent =
      S.spreadIndex + 1 + ' / ' + spreads.length + (fullyPaginated() ? '' : '+');
  }

  // The counter is the page finder: the thing that says where you are is the
  // thing that takes you elsewhere. Click it, type a page, press Enter.
  var counterLabel = document.getElementById('counter');
  var counterInput = document.getElementById('counter-input');

  function closeFinder() {
    counterInput.hidden = true;
    counterLabel.hidden = false;
  }

  function openFinder() {
    if (!S.ready || !spreads.length) return;
    counterLabel.hidden = true;
    counterInput.hidden = false;
    counterInput.value = String(S.spreadIndex + 1);
    counterInput.focus();
    counterInput.select();
  }

  counterLabel.addEventListener('click', openFinder);
  counterInput.addEventListener('blur', closeFinder);

  // Copy a link to the current page. The URL already carries it (persistPosition
  // keeps #p current), so this is just the address bar, handed over on purpose.
  var linkButton = document.getElementById('link-btn');
  var linkFlash = null;
  linkButton.addEventListener('click', function () {
    persistPosition(); // make sure the URL matches this exact page first
    var url = location.href;
    var confirm = function () {
      linkButton.classList.add('copied');
      clearTimeout(linkFlash);
      linkFlash = setTimeout(function () { linkButton.classList.remove('copied'); }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(confirm, function () { prompt('Copy this link:', url); });
    } else {
      prompt('Copy this link:', url);
    }
  });

  // A #p link pasted into an already-open book should navigate too, not just one
  // opened fresh. replaceState (how the URL is kept current) never fires this, so
  // there is no loop.
  window.addEventListener('hashchange', function () {
    // An edits link pasted into an already-open book imports and reflows, rather
    // than being read as page navigation.
    if (REVISE && /[#&]e=/.test(location.hash || '')) {
      importEditsFromHash();
      updateEditsButton();
      if (S.ready) repaginate(currentPosition());
      return;
    }
    var s = stateFromHash();
    if (s && s.pair != null && s.pair !== currentPair()) goToPair(s.pair, false);
  });
  counterInput.addEventListener('keydown', function (e) {
    // While typing, arrows and space belong to the field, not to the book.
    e.stopPropagation();
    if (e.key === 'Enter') {
      var page = parseInt(counterInput.value.replace(/[^0-9]/g, ''), 10);
      closeFinder();
      // goToSpread paginates far enough to reach the page and clamps past the
      // end, so a number beyond the book lands on its last spread.
      if (isFinite(page) && page > 0) goToSpread(page - 1, false);
    } else if (e.key === 'Escape') {
      closeFinder();
    }
  });

  // ---------- bookmarks ----------
  function bookmarkOnSpread(spreadIndex) {
    for (var i = 0; i < S.bookmarks.length; i++) {
      if (spreadCoversPair(spreads[spreadIndex], S.bookmarks[i])) return S.bookmarks[i];
    }
    return -1;
  }

  function toggleBookmark() {
    var existing = bookmarkOnSpread(S.spreadIndex);
    if (existing >= 0) removeBookmark(existing);
    else {
      S.bookmarks = S.bookmarks.concat([currentPair()]).sort(function (a, b) { return a - b; });
      saveBookmarks();
    }
  }

  function removeBookmark(pair) {
    S.bookmarks = S.bookmarks.filter(function (p) { return p !== pair; });
    saveBookmarks();
  }

  function saveBookmarks() {
    lsSet('bookmarks', { v: STORE_VERSION, pairs: S.bookmarks });
    writeUrl(); // the link carries bookmarks, so keep it current as they change
    updateBookmarkStar();
    paintRibbon();
    renderOverlays();
  }

  function updateBookmarkStar() {
    var on = bookmarkOnSpread(S.spreadIndex) >= 0;
    var star = document.getElementById('bm-star');
    star.setAttribute('aria-pressed', on ? 'true' : 'false');
    star.setAttribute('aria-label', on ? i18n('removeBookmark') : i18n('bookmark'));
    var path = document.getElementById('bm-star-path');
    path.setAttribute('fill', on ? '#8a3f42' : 'transparent');
    path.setAttribute('stroke', on ? '#8a3f42' : '#a98f78');
  }

  // ---------- input ----------
  var pressX = 0, pressY = 0;
  function onBookPress(e) { pressX = e.clientX; pressY = e.clientY; }
  function onBookClick(e) {
    if (turning()) return;
    // A press-and-drag is a text selection (highlighting a line to correct it),
    // not a page turn. Some browsers — Safari notably — still fire a click at the
    // end of such a drag and have already collapsed the selection by then, so
    // measure the pointer travel rather than trusting getSelection() to survive.
    if (Math.abs(e.clientX - pressX) > 8 || Math.abs(e.clientY - pressY) > 8) return;
    if (REVISE && e.target.closest && e.target.closest('.revise-undo')) return;
    var box = e.currentTarget.getBoundingClientRect();
    step(e.clientX > box.left + box.width / 2 ? 1 : -1);
  }

  var touchX = 0, touchY = 0;
  function onTouchStart(e) {
    var t = e.changedTouches[0];
    touchX = t.clientX;
    touchY = t.clientY;
  }
  function onTouchEnd(e) {
    if (turning()) return;
    var t = e.changedTouches[0];
    var dx = t.clientX - touchX;
    var dy = t.clientY - touchY;
    if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy)) step(dx < 0 ? 1 : -1);
  }

  function closeOverlays() {
    S.chapOpen = S.bmOpen = S.infoOpen = S.dlOpen = false;
    S.resumePair = null;
    renderOverlays();
  }

  document.addEventListener('keydown', function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    // Typing into a field is never page navigation, whatever the key.
    if (e.target && e.target.tagName === 'INPUT') return;
    if (e.key === 'Escape') { hideTip(); if (REVISE) { hideRevise(); closeKeyPanel(); } closeOverlays(); return; }
    var inControl = e.target && e.target.closest && e.target.closest('button, [role="button"]');
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || e.key === ' ') {
      if (e.key === ' ' && inControl) return; // let Space activate the focused control
      e.preventDefault();
      step(e.shiftKey ? 10 : 1);
    } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
      e.preventDefault();
      step(e.shiftKey ? -10 : -1);
    }
  });

  document.addEventListener('click', function (e) {
    if ((S.bmOpen || S.chapOpen || S.dlOpen) && !e.target.closest('[data-pop]') && !e.target.closest('.popover')) {
      S.bmOpen = S.chapOpen = S.dlOpen = false;
      renderOverlays();
    }
    // The source toggle refreshes the note in place (setSource), so a click on it
    // is not "outside" — it must not close the panel.
    if (S.infoOpen && !e.target.closest('[data-info]') && !e.target.closest('.info-panel')
        && !e.target.closest('.segmented')) {
      S.infoOpen = false;
      renderOverlays();
    }
  }, true);

  document.getElementById('stage-wrap').addEventListener('mouseover', function (e) {
    var host = e.target.closest('[data-pair]');
    if (host) setActive(Number(host.dataset.pair));
  });
  document.getElementById('stage-wrap').addEventListener('mouseout', function (e) {
    var host = e.target.closest('[data-pair]');
    if (host && !host.contains(e.relatedTarget)) clearActive(Number(host.dataset.pair));
  });

  // Watch the stage rather than the window. The book's size is derived from the
  // stage's box (sizeBook) and nothing else, so this reacts to exactly the
  // changes that matter — the header wrapping, the window resizing, and the
  // reader booting before the browser has laid anything out, which would
  // otherwise measure a zero-width page and put one paragraph on every spread.
  // It also ignores the resize events mobile browsers fire when the URL bar
  // hides without changing the box. The stage element is stable across remounts,
  // so it is observed once.
  var layoutTimer = null;
  var layoutObserver = null;
  var lastBox = { width: 0, height: 0 };

  function onLayoutChange() {
    clearTimeout(layoutTimer);
    layoutTimer = setTimeout(function () {
      if (!S.ready) return;
      var stage = document.getElementById('stage-wrap');
      var width = Math.round(stage.clientWidth);
      var height = Math.round(stage.clientHeight);
      if (!width || !height) return;
      // Skip only when there is a laid-out book to keep: an empty `spreads`
      // means pagination never got a usable box, so retry even at the same size.
      if (spreads.length && width === lastBox.width && height === lastBox.height) return;
      lastBox = { width: width, height: height };

      var anchor = currentPosition();
      var mobile = isMobileWidth();
      S.turn = null;
      S.fade = false;
      clearTimeout(transitionTimer);
      if (mobile !== S.mobile) {
        S.mobile = mobile;
        mount();
      }
      measureHeader();
      sizeBook();      // the stage changed, so re-fit the book to it
      applyFontSize(); // then scale the type to the book's new width
      repaginate(anchor);
    }, 120);
  }

  function watchLayout() {
    if (!window.ResizeObserver) return;
    if (layoutObserver) layoutObserver.disconnect();
    layoutObserver = new ResizeObserver(onLayoutChange);
    layoutObserver.observe(document.getElementById('stage-wrap'));
  }

  window.addEventListener('resize', onLayoutChange);

  function changeFontScale(delta) {
    var next = Math.min(1.35, Math.max(0.8, +(S.fontScale + delta).toFixed(2)));
    if (next === S.fontScale) return;
    S.fontScale = next;
    applyFontSize();
    repaginate(currentPosition());
  }
  document.getElementById('font-inc').addEventListener('click', function () { changeFontScale(0.1); });
  document.getElementById('font-dec').addEventListener('click', function () { changeFontScale(-0.1); });

  document.getElementById('blur-toggle').addEventListener('click', function () {
    S.blurEnglish = !S.blurEnglish;
    S.activePair = -1;
    this.textContent = S.blurEnglish ? i18n('showTranslation') : i18n('blur');
    var nodes = document.querySelectorAll('.pair-en, .page-corner-right, .page-num-right');
    for (var i = 0; i < nodes.length; i++) nodes[i].classList.toggle('blurred', S.blurEnglish);
  });

  document.getElementById('gloss-btn').addEventListener('click', glossPage);

  var segTranslation = document.getElementById('seg-translation');
  var segPublished = document.getElementById('seg-published');
  if (SOLO) {
    // A translation the reader brought, set beside the French by position: one
    // honest column, no AI/published toggle to switch between.
    segTranslation.removeAttribute('data-i18n');
    segTranslation.textContent = i18n('publishedPanelTitle');
    segTranslation.style.cursor = 'default';
    segPublished.remove();
    var soloDivider = document.querySelector('.segmented .seg-divider');
    if (soloDivider) soloDivider.remove();
    document.getElementById('info-btn').style.display = 'none';
  } else if (PUBLISHED) {
    segPublished.disabled = false;
    segPublished.removeAttribute('aria-disabled');
    segPublished.removeAttribute('tabindex');
  }
  function setSource(source) {
    if (source === S.source) return;
    if (source === 'published' && !PUBLISHED) return;
    S.source = source;
    segTranslation.setAttribute('aria-pressed', String(source === 'translation'));
    segPublished.setAttribute('aria-pressed', String(source === 'published'));
    // The ⓘ note describes the column you are reading, so refresh it (rather than
    // close it) each time the source changes, however many times you switch.
    if (S.infoOpen) renderOverlays();
    paint({ xfade: true });
  }
  segTranslation.addEventListener('click', function () { setSource('translation'); });
  segPublished.addEventListener('click', function () { setSource('published'); });

  // The crossing to the builder, shown only when this book was built with one to
  // cross to. No URL, no arrow — a book that travels never points at nothing.
  if (DATA.builderUrl) {
    var builderLink = document.getElementById('builder-link');
    builderLink.href = DATA.builderUrl;
    builderLink.hidden = false;
  }

  function togglePanel(name) {
    S.chapOpen = name === 'chap' ? !S.chapOpen : false;
    S.bmOpen = name === 'bm' ? !S.bmOpen : false;
    S.infoOpen = name === 'info' ? !S.infoOpen : false;
    S.dlOpen = name === 'dl' ? !S.dlOpen : false;
    if (S.bmOpen) paginateAll(); // bookmark rows show page numbers
    renderOverlays();
  }
  document.getElementById('chap-btn').addEventListener('click', function (e) { e.stopPropagation(); togglePanel('chap'); });
  document.getElementById('bm-btn').addEventListener('click', function (e) { e.stopPropagation(); togglePanel('bm'); });
  document.getElementById('info-btn').addEventListener('click', function (e) { e.stopPropagation(); togglePanel('info'); });
  document.getElementById('bm-star').addEventListener('click', function (e) { e.stopPropagation(); toggleBookmark(); });

  // The download control appears only when a format was built into the file.
  var downloadButton = document.getElementById('dl-btn');
  if (DOWNLOADS.length) {
    downloadButton.hidden = false;
    downloadButton.addEventListener('click', function (e) { e.stopPropagation(); togglePanel('dl'); });
  }

  // Rebuild the base64 blob into a file and hand it to the browser to save. The
  // bytes are read here, on click, not at load — that is why they sit in their
  // own <script> rather than in the book data.
  var DOWNLOAD_MIME = { epub: 'application/epub+zip', pdf: 'application/pdf' };

  // Hand over the edition the reader has open: a book built with a published
  // translation carries both, so the download follows the source toggle. Falls
  // back to the AI edition, which is always present.
  function downloadEntryFor(format) {
    var pick = function (source) {
      for (var i = 0; i < DOWNLOADS.length; i++) {
        if (DOWNLOADS[i].format === format && DOWNLOADS[i].source === source) return DOWNLOADS[i];
      }
      return null;
    };
    return pick(S.source) || pick('translation');
  }
  function download(format) {
    var entry = downloadEntryFor(format);
    if (!entry) return;
    var blob = document.getElementById('dl-' + format + '-' + entry.source);
    if (!blob) return;
    var binary = atob(blob.textContent.replace(/\s+/g, ''));
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    var url = URL.createObjectURL(
      new Blob([bytes], { type: DOWNLOAD_MIME[format] || 'application/octet-stream' })
    );
    var link = document.createElement('a');
    link.href = url;
    link.download = entry.filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    S.dlOpen = false;
    renderOverlays();
  }

  // ---------- overlays ----------
  function popover() {
    var el = document.createElement('div');
    el.className = 'popover' + (S.mobile ? ' mobile' : '');
    el.setAttribute('data-pop', '1');
    el.addEventListener('click', function (e) { e.stopPropagation(); });
    return el;
  }

  function popoverTitle(text) {
    var el = document.createElement('div');
    el.className = 'popover-title';
    el.textContent = text;
    return el;
  }

  function renderOverlays() {
    var root = document.getElementById('overlay-root');
    root.textContent = '';
    document.getElementById('chap-btn').classList.toggle('active', S.chapOpen);
    document.getElementById('bm-btn').classList.toggle('active', S.bmOpen);
    document.getElementById('info-btn').classList.toggle('active', S.infoOpen);
    document.getElementById('bm-btn').textContent =
      i18n('bookmarks') + (S.bookmarks.length ? ' · ' + S.bookmarks.length : '');
    var dl = document.getElementById('dl-btn');
    if (dl) {
      dl.classList.toggle('active', S.dlOpen);
      dl.setAttribute('aria-expanded', S.dlOpen ? 'true' : 'false');
    }

    if (S.chapOpen) root.appendChild(renderChapterList());
    if (S.bmOpen) root.appendChild(renderBookmarkList());
    if (S.infoOpen) root.appendChild(renderInfoPanel());
    if (S.dlOpen) root.appendChild(renderDownloadMenu());
    if (S.resumePair != null) root.appendChild(renderResumeBanner());
  }

  function renderDownloadMenu() {
    var pop = popover();
    pop.classList.add('dl-menu');
    pop.appendChild(popoverTitle(i18n('downloadTitle')));
    // One row per format, even when a format carries both editions — which one
    // saves is decided at click time by the open source, not by the menu.
    var formats = [];
    DOWNLOADS.forEach(function (e) { if (formats.indexOf(e.format) === -1) formats.push(e.format); });
    formats.forEach(function (format) {
      var meta = DOWNLOAD_LABELS[format] || { title: String(format).toUpperCase(), sub: '' };
      var row = document.createElement('button');
      row.className = 'popover-row';
      var title = document.createElement('div');
      title.className = 'eyebrow-sm';
      title.textContent = meta.title;
      var sub = document.createElement('div');
      sub.className = 'sub';
      sub.textContent = i18n(format + 'Sub') || meta.sub;
      row.appendChild(title);
      row.appendChild(sub);
      row.addEventListener('click', function () { download(format); });
      pop.appendChild(row);
    });
    return pop;
  }

  function renderChapterList() {
    var pop = popover();
    pop.appendChild(popoverTitle(i18n('chapters')));
    var current = chapterForPair(currentPair());
    CHAPTERS.forEach(function (chapter) {
      var row = document.createElement('button');
      row.className = 'popover-row' + (chapter === current ? ' active' : '');
      var eyebrow = document.createElement('div');
      eyebrow.className = 'eyebrow-sm';
      eyebrow.textContent = chapter.frEyebrow;
      var sub = document.createElement('div');
      sub.className = 'sub';
      sub.textContent = chapter.frTitle;
      row.appendChild(eyebrow);
      row.appendChild(sub);
      row.addEventListener('click', function () {
        S.chapOpen = false;
        renderOverlays();
        goToPair(chapter.pair, false);
      });
      pop.appendChild(row);
    });
    return pop;
  }

  function renderBookmarkList() {
    var pop = popover();
    pop.appendChild(popoverTitle(i18n('bookmarks')));
    if (!S.bookmarks.length) {
      var empty = document.createElement('div');
      empty.className = 'popover-empty';
      empty.textContent = i18n('noBookmarks');
      pop.appendChild(empty);
      if (SYNC.offered) pop.appendChild(renderSyncFoot());
      return pop;
    }
    S.bookmarks.forEach(function (pair) {
      var spreadIndex = spreadIndexForPair(pair);
      var chapter = chapterForPair(pair);
      var row = document.createElement('div');
      row.className = 'bm-row';

      var go = document.createElement('button');
      go.className = 'popover-row' + (spreadIndex === S.spreadIndex ? ' active' : '');
      var ref = document.createElement('span');
      ref.className = 'page-ref';
      ref.textContent = i18n('pageAbbr') + ' ' + (spreadIndex + 1);
      var title = document.createElement('span');
      title.className = 'chapter-ref';
      title.textContent = chapter ? chapter.frTitle : '';
      go.appendChild(ref);
      go.appendChild(title);
      go.addEventListener('click', function () {
        S.bmOpen = false;
        renderOverlays();
        goToPair(pair, false);
      });

      var remove = document.createElement('button');
      remove.className = 'bm-remove';
      remove.setAttribute('aria-label', i18n('removeBookmark'));
      remove.textContent = '×';
      remove.addEventListener('click', function (e) {
        e.stopPropagation();
        removeBookmark(pair);
      });

      row.appendChild(go);
      row.appendChild(remove);
      pop.appendChild(row);
    });
    if (SYNC.offered) pop.appendChild(renderSyncFoot());
    return pop;
  }

  // Sync lives at the foot of this panel because it is the same subject the
  // panel is already about: where you are in the book.
  function renderSyncFoot() {
    var foot = document.createElement('div');
    foot.className = 'sync-foot';

    var line = document.createElement('div');
    line.className = 'sync-line';
    line.textContent = SYNC.signedIn
      ? i18n('syncKept').replace('{handle}', SYNC.handle)
      : i18n('syncOffer');

    var act = document.createElement('button');
    act.className = 'sync-act';
    act.textContent = i18n(SYNC.signedIn ? 'syncSignOut' : 'syncSignIn');
    act.addEventListener('click', function (e) {
      e.stopPropagation();
      if (SYNC.signedIn) signOut(); else signIn();
    });

    foot.appendChild(line);
    foot.appendChild(act);
    return foot;
  }

  function renderInfoPanel() {
    var panel = document.createElement('div');
    panel.className = 'info-panel' + (S.mobile ? ' mobile' : '');
    panel.setAttribute('data-info', '1');
    panel.addEventListener('click', function (e) { e.stopPropagation(); });

    var close = document.createElement('button');
    close.className = 'info-close';
    close.setAttribute('aria-label', i18n('close'));
    close.textContent = '×';
    close.addEventListener('click', function () { S.infoOpen = false; renderOverlays(); });

    var title = document.createElement('div');
    title.className = 'info-title';
    var rule = document.createElement('div');
    rule.className = 'info-rule';
    var body = document.createElement('div');
    body.className = 'info-body';
    var foot = document.createElement('div');
    foot.className = 'info-foot';

    panel.appendChild(close);
    panel.appendChild(title);
    panel.appendChild(rule);
    panel.appendChild(body);

    if (PUBLISHED) {
      // The note names and follows whichever column you are reading — the
      // generated one, or the published edition you brought.
      var onPublished = S.source === 'published';
      title.textContent = onPublished ? i18n('publishedPanelTitle') : i18n('translation');
      body.textContent = onPublished
        ? (DATA.publishedNote || i18n('publishedToggleHint'))
        : i18n('publishedToggleHint');
      foot.textContent = i18n('privacyFoot');
      panel.appendChild(foot);
    } else {
      title.textContent = i18n('publishedPanelTitle');
      body.textContent = i18n('bringYourOwn');
      var command = document.createElement('div');
      command.className = 'info-cmd';
      command.textContent = 'python -m biread french.txt --published english.txt';
      foot.textContent = i18n('privacyFoot');
      panel.appendChild(command);
      panel.appendChild(foot);
    }
    return panel;
  }

  function renderResumeBanner() {
    var pair = S.resumePair;
    var chapter = chapterForPair(pair);
    var banner = document.createElement('div');
    banner.className = 'resume-banner';

    var text = document.createElement('span');
    text.textContent = i18n('resume');
    var highlight = document.createElement('span');
    highlight.className = 'hl';
    highlight.textContent = chapter && chapter.frTitle ? ' — ' + chapter.frTitle : '';
    text.appendChild(highlight);

    var resume = document.createElement('button');
    resume.className = 'resume-go';
    resume.textContent = i18n('resumeButton');
    resume.addEventListener('click', function () {
      var target = position(S.resumePair, S.resumeFrac);
      S.resumePair = null;
      renderOverlays();
      goToPosition(target, false);
    });

    var dismiss = document.createElement('button');
    dismiss.className = 'resume-x';
    dismiss.setAttribute('aria-label', i18n('dismiss'));
    dismiss.textContent = '×';
    dismiss.addEventListener('click', function () { S.resumePair = null; renderOverlays(); });

    banner.appendChild(text);
    banner.appendChild(resume);
    banner.appendChild(dismiss);
    return banner;
  }

  // ---------- sync ----------
  // A book served over http(s) asks its own host, once, whether it keeps places.
  // A file opened from the desktop asks nobody anything — that a downloaded book
  // phones nowhere is most of why it is one file. Everything below is therefore
  // silent when the host does not answer, or answers that sign-in is not set up.
  var SYNC = { offered: false, signedIn: false, handle: '', bookId: '', timer: null };

  // Not a security boundary — an identity. Two 32-bit passes over the text, which
  // is why crypto.subtle is not used: it is absent outside a secure context, and
  // a book served over plain http would lose sync for a hash that guards nothing.
  function textHash(s) {
    var a = 0x811c9dc5, b = 0x27d4eb2f;
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      a = Math.imul(a ^ c, 0x01000193) >>> 0;
      b = Math.imul(b + c, 0x85ebca6b) >>> 0;
    }
    return ('0000000' + a.toString(16)).slice(-8) + ('0000000' + b.toString(16)).slice(-8);
  }

  // A paragraph's own name. Books built with --revise carry one; the rest are
  // named by their text, so a book made before any of this still syncs.
  var paraKeys = null;
  function paraKey(i) {
    if (!paraKeys) paraKeys = [];
    if (paraKeys[i] == null) paraKeys[i] = PAIRS[i].h || textHash(PAIRS[i].fr || '');
    return paraKeys[i];
  }
  function pairForKey(key) {
    for (var i = 0; i < PAIRS.length; i++) if (paraKey(i) === key) return i;
    return -1;
  }
  function bookIdentity() {
    var fr = [];
    for (var i = 0; i < PAIRS.length; i++) fr.push(PAIRS[i].fr || '');
    return textHash(fr.join('\n')) + '-' + PAIRS.length;
  }

  function syncGet(path) {
    return fetch(path, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function syncStart() {
    if (!/^https?:$/.test(location.protocol)) return;
    syncGet('/api/health').then(function (health) {
      // No sync service, or one with no way in: say nothing rather than offer a
      // button that fails.
      if (!health || !health.ok || !health.signIn) return;
      SYNC.offered = true;
      SYNC.bookId = bookIdentity();
      return syncGet('/api/me').then(function (me) {
        SYNC.signedIn = !!(me && me.signedIn);
        SYNC.handle = (me && me.handle) || '';
        renderOverlays();
        if (SYNC.signedIn) syncPull();
      });
    });
  }

  function syncPull() {
    syncGet('/api/shelf').then(function (data) {
      if (!data || !data.books) return;
      var mine = null;
      for (var i = 0; i < data.books.length; i++) {
        if (data.books[i].bookId === SYNC.bookId) mine = data.books[i];
      }
      if (!mine) return syncPush();   // first sight of this book — put it up
      adoptEdits(mine.edits || []);
      adoptPosition(mine.position);
    });
  }

  // Never a silent jump. Where another device stopped is offered through the
  // same banner a returning reader already knows, and declined by ignoring it.
  function adoptPosition(pos) {
    if (!pos || !pos.h || !S.ready) return;
    var i = pairForKey(pos.h);
    if (i < 0 || i === currentPair()) return;
    S.resumePair = i;
    S.resumeFrac = typeof pos.frac === 'number' ? pos.frac : 0;
    renderOverlays();
  }

  // A correction arrives as the sentence its reader wrote plus a hash of the
  // paragraph it replaced. If that hash is not the paragraph this book holds,
  // the fix was made against different prose and is dropped — the same staleness
  // rule the local store already applies, carried over the wire.
  function adoptEdits(edits) {
    if (!REVISE || !edits.length) return;
    var changed = false;
    for (var n = 0; n < edits.length; n++) {
      var e = edits[n], i = pairForKey(e.h);
      if (i < 0 || textHash(PAIRS[i].en || '') !== e.baseHash) continue;
      var when = Date.parse(e.updatedAt) || 0, held = overrides[e.h];
      if (held && (held.at || 0) >= when) continue;
      overrides[e.h] = { base: PAIRS[i].en, text: e.text, at: when };
      changed = true;
    }
    if (!changed) return;
    saveOverrides();
    updateEditsButton();
    repaginate(currentPosition());
  }

  function syncSoon() {
    if (!SYNC.signedIn) return;
    clearTimeout(SYNC.timer);
    SYNC.timer = setTimeout(syncPush, 2500);
  }

  function syncPush() {
    if (!SYNC.signedIn || !SYNC.bookId) return;
    var pos = currentPosition();
    var body = {
      title: DATA.titleFr || null,
      lang: DATA.lang || null,
      position: { h: paraKey(pos.p), frac: pos.f },
      updatedAt: new Date().toISOString(),
      edits: pendingEdits(),
    };
    fetch('/api/shelf/' + encodeURIComponent(SYNC.bookId), {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) {
      // A session that has run out is not an error to shout about: fold the
      // offer back to signed-out and let the reader sign in again when they like.
      if (r.status === 401) { SYNC.signedIn = false; renderOverlays(); }
    }).catch(function () {});
  }

  function pendingEdits() {
    if (!REVISE) return [];
    var out = [];
    for (var h in overrides) {
      var ov = overrides[h];
      if (!ov || typeof ov.text !== 'string') continue;
      out.push({ h: h, baseHash: textHash(ov.base || ''), text: ov.text,
                 updatedAt: new Date(ov.at || Date.now()).toISOString() });
      if (out.length >= 500) break;   // the server's ceiling; see server/shelf.py
    }
    return out;
  }

  function signIn() {
    location.href = '/api/auth/github?next='
      + encodeURIComponent(location.pathname + location.search);
  }
  function signOut() {
    fetch('/api/auth/signout', { method: 'POST', credentials: 'same-origin' })
      .then(function () {
        SYNC.signedIn = false;
        SYNC.handle = '';
        renderOverlays();
      }).catch(function () {});
  }

  // ---------- boot ----------
  function boot() {
    applyStaticLabels();
    if (REVISE) { loadOverrides(); importEditsFromHash(); updateEditsButton(); }
    if (GLOSS) loadBoughtGlosses();
    if (REVISE || GLOSS) apiKey = loadKey();
    var storedBookmarks = lsGet('bookmarks');
    if (storedBookmarks && Array.isArray(storedBookmarks.pairs)) {
      S.bookmarks = storedBookmarks.pairs.filter(function (p) {
        return typeof p === 'number' && p >= 0 && p < PAIRS.length;
      });
    }
    var storedPosition = lsGet('last');
    var resumePair =
      storedPosition && typeof storedPosition.pair === 'number' ? storedPosition.pair : 0;
    var resumeFrac =
      storedPosition && typeof storedPosition.frac === 'number' ? storedPosition.frac : 0;
    // A shared link says "take me here", so it wins over the local memory and
    // goes straight there rather than offering to resume. Any bookmarks it
    // carries are merged in — non-destructive, so the reader keeps their own.
    var linked = stateFromHash();
    if (linked && linked.bookmarks.length) {
      var union = {};
      S.bookmarks.concat(linked.bookmarks).forEach(function (p) { union[p] = 1; });
      S.bookmarks = Object.keys(union).map(Number).sort(function (a, b) { return a - b; });
      lsSet('bookmarks', { v: STORE_VERSION, pairs: S.bookmarks });
    }

    measureHeader();
    S.mobile = isMobileWidth();
    mount();
    sizeBook();      // give the book its box before anything measures against it
    applyFontSize(); // after sizeBook: the type is derived from the book's width
    buildProbe();
    paginateNextSection(); // first section synchronously so the book opens now
    S.ready = true;
    S.spreadIndex = 0;
    if (linked && linked.pair != null) {
      goToPair(linked.pair, false);
    } else if (resumePair < PAIRS.length && (resumePair > 0 || resumeFrac > 0)) {
      S.resumePair = resumePair;
      S.resumeFrac = resumeFrac;
    }
    paint();
    renderOverlays();
    scheduleBackgroundPagination();

    // Record what we just laid out against. If it was nothing — a book opened
    // before the browser sized the viewport — the watcher sees the real stage
    // box arrive and repaginates.
    var stage = document.getElementById('stage-wrap');
    lastBox = { width: Math.round(stage.clientWidth), height: Math.round(stage.clientHeight) };
    watchLayout();
    syncStart();
  }

  // A page closed mid-debounce would otherwise lose the last page turn, which is
  // exactly the one a reader wants on the other device.
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'hidden' && SYNC.timer) {
      clearTimeout(SYNC.timer);
      SYNC.timer = null;
      syncPush();
    }
  });

  if (document.fonts && document.fonts.ready) {
    // Fonts are inlined, so this settles immediately — the timeout only stops a
    // stalled font from leaving the reader on its loading message forever.
    var started = false;
    var start = function () { if (!started) { started = true; boot(); } };
    document.fonts.ready.then(start);
    setTimeout(start, 3000);
  } else {
    boot();
  }
})();
