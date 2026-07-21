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
  var FIT_MARGIN = 8; // px of slack between the measured fit and the page

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
  var backgroundTimer = null;
  var transitionTimer = null;
  var probe = {};
  var view = {}; // the mounted book: page nodes, ribbon host

  // Type scales with the book, so a smaller book keeps the same number of
  // characters per line instead of turning into a narrow ribbon of text.
  // 1060px of book lands on the design's 20px; the cap lets a wide-screen spread
  // grow a little more instead of flattening into over-long lines.
  function fpx() {
    var width = view.book ? view.book.getBoundingClientRect().width : 1060;
    var base = Math.max(15, Math.min(23, width / 53));
    return Math.round(base * S.fontScale);
  }

  function applyFontSize() {
    document.documentElement.style.setProperty('--fpx', fpx() + 'px');
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

  // ---------- content ----------
  function englishText(i) {
    if (S.source === 'published' && PAIRS[i].pub) return PAIRS[i].pub;
    return PAIRS[i].en;
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

  function mobilePairNode(i, french, english, continued) {
    var box = document.createElement('div');
    box.className = 'mobile-pair';
    box.dataset.pair = i;
    box.appendChild(paragraphNode(i, 'fr', french, continued));
    box.appendChild(paragraphNode(i, 'en', english, continued));
    return box;
  }

  // ---------- positions ----------
  // A position is a paragraph and how far through it: {p: index, f: 0..1}. A
  // paragraph too tall for one page continues onto the next, so a spread spans
  // two positions rather than covering a whole number of paragraphs.
  function position(p, f) { return { p: p, f: f }; }

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
      target.appendChild(
        paragraphNode(p, side, textSpan(englishText(p), from, to), continued)
      );
    });
  }

  function fillMobileColumn(target, spread, chapter) {
    if (chapter) target.appendChild(headingNode(chapter, 'fr'));
    if (!spread) return;
    var first = true;
    eachPart(spread, function (p, from, to, continued) {
      if (!first) target.appendChild(dividerNode());
      target.appendChild(mobilePairNode(
        p, textSpan(PAIRS[p].fr, from, to), textSpan(englishText(p), from, to), continued
      ));
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
      return [{ mobile: true, english: function (i) { return PAIRS[i].en; } }];
    }
    return [
      { side: 'fr', text: function (i) { return PAIRS[i].fr; } },
      { side: 'en', text: function (i) { return PAIRS[i].en; } }
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
    var limit = available - FIT_MARGIN;

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
              p, textSpan(PAIRS[p].fr, a, b), textSpan(column.english(p), a, b), continued
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
    lsSet('last', { v: STORE_VERSION, pair: currentPair() });
    writeUrl();
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

  // ---------- mounting ----------
  function mount() {
    var wrap = document.getElementById('stage-wrap');
    wrap.className = S.mobile ? 'mobile' : '';
    wrap.textContent = '';

    var book = document.createElement('div');
    book.className = S.mobile ? 'book-mobile' : 'book-desk';
    book.addEventListener('click', onBookClick);
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
    updateCounter();
    updateBookmarkStar();
    view.book.style.opacity = S.fade ? '0' : '1';
    if (S.mobile) paintMobile(options); else paintDesk(options);
    paintRibbon();
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
  function onBookClick(e) {
    if (turning()) return;
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
    if (e.key === 'Escape') { hideTip(); closeOverlays(); return; }
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

  var segTranslation = document.getElementById('seg-translation');
  var segPublished = document.getElementById('seg-published');
  if (PUBLISHED) {
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
  function download(entry) {
    var blob = document.getElementById('dl-' + entry.format);
    if (!blob) return;
    var binary = atob(blob.textContent.replace(/\s+/g, ''));
    var bytes = new Uint8Array(binary.length);
    for (var i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    var url = URL.createObjectURL(
      new Blob([bytes], { type: DOWNLOAD_MIME[entry.format] || 'application/octet-stream' })
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
    DOWNLOADS.forEach(function (entry) {
      var meta = DOWNLOAD_LABELS[entry.format] ||
        { title: String(entry.format).toUpperCase(), sub: '' };
      var row = document.createElement('button');
      row.className = 'popover-row';
      var title = document.createElement('div');
      title.className = 'eyebrow-sm';
      title.textContent = meta.title;
      var sub = document.createElement('div');
      sub.className = 'sub';
      sub.textContent = i18n(entry.format + 'Sub') || meta.sub;
      row.appendChild(title);
      row.appendChild(sub);
      row.addEventListener('click', function () { download(entry); });
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
    return pop;
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
      var target = S.resumePair;
      S.resumePair = null;
      renderOverlays();
      goToPair(target, false);
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

  // ---------- boot ----------
  function boot() {
    applyStaticLabels();
    var storedBookmarks = lsGet('bookmarks');
    if (storedBookmarks && Array.isArray(storedBookmarks.pairs)) {
      S.bookmarks = storedBookmarks.pairs.filter(function (p) {
        return typeof p === 'number' && p >= 0 && p < PAIRS.length;
      });
    }
    var storedPosition = lsGet('last');
    var resumePair =
      storedPosition && typeof storedPosition.pair === 'number' ? storedPosition.pair : 0;
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
    } else if (resumePair > 0 && resumePair < PAIRS.length) {
      S.resumePair = resumePair;
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
  }

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
