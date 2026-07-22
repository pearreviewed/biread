"""A fixed-layout EPUB: the French on the left page, the English on the right,
locked as a spread and paginated the way the on-screen reader paginates.

A reflowable e-book hands its page breaks to the reading system, so it cannot
hold a French page facing its English one — the parallel spread the reader is
built around. A fixed-layout book can: every page is a pre-measured canvas, and
French and English are paired left and right. The price is that the type has to
be measured at build time, so this — like the PDF — needs the headless browser
(the ``[browser]`` extra); the import is deferred to where it is used.

Glosses are left out on purpose, exactly as they are in the PDF. A tap target on
every phrase turns the page into a wall of links (Apple Books paints them the
same blue as a hyperlink) and buries the text. Hover-glossing is the reader's
job, where it costs nothing and asks for nothing.

Pagination is the reader's own algorithm (fits / spreadEnd from reader.js),
ported and run in headless Chromium so a page holds what the reader's page holds:
whole paragraphs while they fit, then a binary search for the largest fraction of
the next one that still fits *both* columns, so French and English break at the
same point and meet again where the paragraph ends.
"""
from __future__ import annotations

import base64
import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ..cleanup import Chapter
from ..errors import BireadError
from ..targets import ENGLISH, Target
from ..translate import hash_text

ASSETS = Path(__file__).parent.parent / "assets"
FONTS = ASSETS / "fonts"

# The spread is the reader's 7:5 open book; a page is half of it. The type scale
# is the reader's own (fpx = clamp(15, 23, spread_width / 53)), so a line holds
# the same number of characters it does on screen.
SPREAD_W = 1200
PAGE_W = SPREAD_W // 2
PAGE_H = round(SPREAD_W * 5 / 7)
FPX = round(max(15, min(23, SPREAD_W / 53)))

# The page's look, shared by the measurement harness and the emitted pages so the
# two can never disagree about how much room a page has. The type, paper and
# heading values mirror reader.css — that stylesheet still governs the look.
STYLESHEET = """\
@font-face { font-family: 'EB Garamond'; font-style: normal; font-weight: 400;
  src: url(data:font/woff2;base64,@@FONT_REGULAR@@) format('woff2'); }
@font-face { font-family: 'EB Garamond'; font-style: italic; font-weight: 400;
  src: url(data:font/woff2;base64,@@FONT_ITALIC@@) format('woff2'); }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; height: 100%; }
:root { --fpx: @@FPX@@px; }
.page { position: absolute; inset: 0; overflow: hidden; font-family: 'EB Garamond', Georgia, serif;
  padding: calc(var(--fpx) * 2.2) calc(var(--fpx) * 2.9) calc(var(--fpx) * 2);
  background-color: #fdf4ee; background-image: url(paper.png),
  radial-gradient(170% 125% at 98% 50%, #fdf5ef 0%, #fbf1e7 97.5%, #f0dcc8 99.4%, #caa885 100%);
  box-shadow: inset -20px 0 34px -20px rgba(70,45,15,.30); }
.page-right { background-image: url(paper.png),
  radial-gradient(170% 125% at 2% 50%, #fdf5ef 0%, #fbf1e7 97.5%, #f0dcc8 99.4%, #caa885 100%);
  box-shadow: inset 20px 0 34px -20px rgba(70,45,15,.30); }
.chapter-heading { margin-bottom: 14px; }
.ch-eyebrow { font-size: calc(var(--fpx) * 0.6); letter-spacing: .32em; text-transform: uppercase;
  color: #8a7551; font-weight: 600; }
.ch-title { font-size: calc(var(--fpx) * 1.32); line-height: 1.12; margin: 7px 0 0; color: #2a1f12;
  font-weight: 600; }
.ch-rule { height: 1px; background: linear-gradient(90deg, #b7a67f, transparent); margin: 16px 0 0; }
p.pair { margin: 0 0 0.34em; font-size: var(--fpx); line-height: 1.38; text-align: justify;
  text-indent: 1.4em; hyphens: auto; }
p.pair.continued { text-indent: 0; }
p.pair-fr { color: #332a1d; }
p.pair-en { color: #4b4335; }
.corner { position: absolute; top: calc(var(--fpx) * 1.05); font-size: 9px; letter-spacing: .3em;
  text-transform: uppercase; color: #9c8a66; }
.corner-left { left: calc(var(--fpx) * 2.9); }
.corner-right { right: calc(var(--fpx) * 2.9); }
.folio { position: absolute; bottom: calc(var(--fpx) * 1.05); font-size: 13px; letter-spacing: .2em;
  color: #9c8a66; }
.folio-left { left: calc(var(--fpx) * 2.9); }
.folio-right { right: calc(var(--fpx) * 2.9); }
.titlepage { height: 100%; display: flex; flex-direction: column; align-items: center;
  justify-content: center; text-align: center; }
.tp-title { font-size: calc(var(--fpx) * 1.9); font-weight: 600; color: #2a1f12; margin: 0 0 .5em; }
.tp-author { font-size: calc(var(--fpx) * 1.05); color: #5a4f3d; margin: 0 0 2.5em; }
.tp-byline { font-size: calc(var(--fpx) * 0.62); letter-spacing: .24em; text-transform: uppercase;
  color: #8a7551; }
"""

# Two 600×857 page boxes side by side, offscreen — French and English measured at
# the same candidate so their break point is chosen from whichever fills first.
# Flex, not nowrap: nowrap would inherit into the paragraphs and stop the text
# wrapping, so a whole chapter would look like it fits one line.
HARNESS_WRAP = """
#stage { position: absolute; left: -20000px; top: 0; display: flex; }
.pgbox { position: relative; flex: 0 0 auto; width: @@PAGE_W@@px; height: @@PAGE_H@@px; }
"""

# A faithful port of reader.js fits / spreadEnd. It returns the actual sliced text
# per column, so what was measured is exactly what gets written.
PAGINATE_JS = r"""
(function (PAIRS, CHAPTERS, LANG) {
  var frInner = document.getElementById('fr-inner');
  var enInner = document.getElementById('en-inner');
  var frPage = frInner.parentNode, enPage = enInner.parentNode;
  var FIT_MARGIN = 8;

  function usable(page) {
    var cs = getComputedStyle(page);
    return page.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  }
  function sliceAt(text, f) {
    if (f <= 0) return 0;
    if (f >= 1) return text.length;
    var s = text.indexOf(' ', Math.round(text.length * f));
    return s === -1 ? text.length : s + 1;
  }
  function span(text, a, b) { return text.slice(sliceAt(text, a), sliceAt(text, b)).trim(); }
  function pos(p, f) { return { p: p, f: f }; }
  function heading(chapter, side) {
    var h = document.createElement('div'); h.className = 'chapter-heading';
    h.lang = side === 'en' ? 'en' : 'fr';
    var e = document.createElement('div'); e.className = 'ch-eyebrow';
    e.textContent = side === 'en' ? chapter.enEyebrow : chapter.frEyebrow;
    var t = document.createElement('div'); t.className = 'ch-title';
    t.textContent = side === 'en' ? chapter.enTitle : chapter.frTitle;
    var r = document.createElement('div'); r.className = 'ch-rule';
    h.appendChild(e); h.appendChild(t); h.appendChild(r); return h;
  }
  function para(p, side, text, continued) {
    var n = document.createElement('p');
    n.className = 'pair pair-' + side + (continued ? ' continued' : '');
    n.lang = side === 'en' ? LANG : 'fr';
    n.textContent = text; return n;
  }
  function eachPart(spread, cb) {
    for (var p = spread.from.p; p <= spread.to.p && p < PAIRS.length; p++) {
      var a = p === spread.from.p ? spread.from.f : 0;
      var b = p === spread.to.p ? spread.to.f : 1;
      if (b <= a) continue;
      cb(p, a, b, a > 0);
    }
  }
  function fill(inner, side, chapter, spread, withHeading) {
    inner.textContent = '';
    if (withHeading && chapter) inner.appendChild(heading(chapter, side));
    eachPart(spread, function (p, a, b, cont) {
      var text = side === 'fr' ? PAIRS[p].fr : PAIRS[p].en;
      inner.appendChild(para(p, side, span(text, a, b), cont));
    });
  }
  function fits(from, to, chapter, withHeading) {
    var limit = usable(frPage) - FIT_MARGIN;
    var sp = { from: from, to: to };
    fill(frInner, 'fr', chapter, sp, withHeading);
    if (frInner.offsetHeight > limit) return false;
    fill(enInner, 'en', chapter, sp, withHeading);
    return enInner.offsetHeight <= limit;
  }
  function spreadEnd(from, end, chapter, withHeading) {
    var whole = null;
    for (var p = from.p; p < end; p++) {
      var cand = pos(p + 1, 0);
      if (!fits(from, cand, chapter, withHeading)) break;
      whole = cand;
    }
    if (whole && whole.p >= end) return whole;
    var splitPair = whole ? whole.p : from.p;
    if (splitPair >= end) return whole || pos(end, 0);
    var low = splitPair === from.p ? from.f : 0, high = 1, best = -1;
    for (var s = 0; s < 12; s++) {
      var mid = (low + high) / 2;
      if (fits(from, pos(splitPair, mid), chapter, withHeading)) { best = mid; low = mid; }
      else high = mid;
    }
    if (best < 0) { if (whole) return whole; best = from.f + 0.05; }
    if (splitPair === from.p && best <= from.f) best = from.f + 0.05;
    best = Math.min(best, 1);
    return best >= 0.999 ? pos(splitPair + 1, 0) : pos(splitPair, best);
  }

  // Each chapter forces a fresh spread, so pagination runs one section at a time.
  var starts = [0];
  CHAPTERS.forEach(function (c) { if (starts.indexOf(c.pair) === -1) starts.push(c.pair); });
  starts.sort(function (a, b) { return a - b; });
  var spreads = [];
  for (var i = 0; i < starts.length; i++) {
    var start = starts[i], fin = i + 1 < starts.length ? starts[i + 1] : PAIRS.length;
    if (start >= fin) continue;
    var chapter = null;
    CHAPTERS.forEach(function (c) { if (c.pair === start) chapter = c; });

    var cursor = pos(start, 0), first = true, guard = 0;
    while (cursor.p < fin && guard++ < 10000) {
      var to = spreadEnd(cursor, fin, chapter, first);
      var sp = { from: cursor, to: to, chapter: first ? chapter : null };
      var fr = [], en = [];
      eachPart(sp, function (p, a, b, cont) {
        fr.push({ text: span(PAIRS[p].fr, a, b), continued: cont });
        en.push({ text: span(PAIRS[p].en, a, b), continued: cont });
      });
      sp.fr = fr; sp.en = en;
      spreads.push(sp);
      cursor = to; first = false;
    }
  }
  return spreads;
})
"""


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _stylesheet() -> str:
    return (STYLESHEET
            .replace("@@FPX@@", str(FPX))
            .replace("@@FONT_REGULAR@@", _b64(FONTS / "eb-garamond-400.woff2"))
            .replace("@@FONT_ITALIC@@", _b64(FONTS / "eb-garamond-400-italic.woff2")))


def _book_pairs(chapters: list[Chapter], translations: dict[str, str],
                target: Target) -> tuple[list[dict], list[dict]]:
    """A flat French/English pair list, and the chapters that break it into
    spreads — the same shape the reader paginates from."""
    pairs: list[dict] = []
    chapter_meta: list[dict] = []
    for chapter in chapters:
        if chapter.number:
            chapter_meta.append({
                "pair": len(pairs),
                "frEyebrow": f"Chapitre {chapter.number}",
                "frTitle": chapter.title or "",
                "enEyebrow": f"{target.chapter_word} {chapter.number}",
                "enTitle": translations.get(hash_text(chapter.title), "") if chapter.title else "",
            })
        for paragraph in chapter.paragraphs:
            pairs.append({"fr": paragraph, "en": translations.get(hash_text(paragraph), "")})
    return pairs, chapter_meta


def _paginate(pairs: list[dict], chapters: list[dict], lang: str) -> list[dict]:
    """Lay the book out into spreads in headless Chromium, using the reader's
    algorithm against the real page CSS. Needs the ``[browser]`` extra."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise BireadError(
            "EPUB export needs the browser engine to lay the spread out. Install it with:\n"
            '  pip install -e ".[browser]" && playwright install chromium'
        ) from e

    css = _stylesheet() + HARNESS_WRAP.replace("@@PAGE_W@@", str(PAGE_W)).replace(
        "@@PAGE_H@@", str(PAGE_H))
    harness = (
        f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><style>{css}</style>'
        '</head><body><div id="stage">'
        '<div class="pgbox"><div class="page page-left"><div id="fr-inner"></div></div></div>'
        '<div class="pgbox"><div class="page page-right"><div id="en-inner"></div></div></div>'
        '</div></body></html>'
    )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1600, "height": 1000})
                page.set_content(harness, wait_until="load")
                page.evaluate("() => document.fonts.ready")
                return page.evaluate(
                    f"([pairs, chapters, lang]) => {PAGINATE_JS}(pairs, chapters, lang)",
                    [pairs, chapters, lang],
                )
            finally:
                browser.close()
    except BireadError:
        raise
    except Exception as e:
        raise BireadError(
            f"EPUB export failed while laying out the spread: {e}\n"
            "If this is the first run, the browser may be missing: playwright install chromium"
        ) from e


def _column_html(parts: list[dict], side: str, chapter: dict | None, folio: int) -> str:
    out: list[str] = []
    if chapter:
        eyebrow = _esc(chapter["frEyebrow"] if side == "fr" else chapter["enEyebrow"])
        title = _esc(chapter["frTitle"] if side == "fr" else chapter["enTitle"])
        out.append(f'<div class="chapter-heading"><div class="ch-eyebrow">{eyebrow}</div>'
                   f'<div class="ch-title">{title}</div><div class="ch-rule"></div></div>')
    lang = "fr" if side == "fr" else "en"
    for part in parts:
        continued = " continued" if part["continued"] else ""
        out.append(f'<p class="pair pair-{side}{continued}" lang="{lang}">{_esc(part["text"])}</p>')
    edge = "left" if side == "fr" else "right"
    out.append(f'<div class="corner corner-{edge}">{"FR" if side == "fr" else "EN"}</div>')
    out.append(f'<div class="folio folio-{edge}">{folio}</div>')
    return "".join(out)


def _page_doc(page_class: str, inner: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="fr"><head><meta charset="utf-8"/>'
        f'<meta name="viewport" content="width={PAGE_W}, height={PAGE_H}"/>'
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>'
        f'<body><div class="page {page_class}">{inner}</div></body></html>\n'
    )


def _titlepage_doc(title: str, author: str) -> str:
    author_line = f'<div class="tp-author">{_esc(author)}</div>' if author else ""
    inner = (f'<div class="titlepage"><div class="tp-title">{_esc(title)}</div>'
             f'{author_line}<div class="tp-byline">Lecteur bilingue</div></div>')
    return _page_doc("titlepage", inner)


def _opf(title: str, book_id: str, author: str, spread_count: int) -> str:
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = [
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '    <item id="css" href="style.css" media-type="text/css"/>',
        '    <item id="paper" href="paper.png" media-type="image/png"/>',
        '    <item id="titlepage" href="titlepage.xhtml" media-type="application/xhtml+xml"/>',
    ]
    spine = ['    <itemref idref="titlepage" properties="rendition:page-spread-center"/>']
    for i in range(spread_count):
        for side, spread in (("L", "left"), ("R", "right")):
            name = f"p{i}{side}"
            manifest.append(
                f'    <item id="{name}" href="{name}.xhtml" media-type="application/xhtml+xml"/>')
            spine.append(f'    <itemref idref="{name}" properties="page-spread-{spread}"/>')
    # The author, with the MARC "aut" role so a library shelves the book correctly.
    creator = (
        f'    <dc:creator id="creator">{_esc(author)}</dc:creator>\n'
        '    <meta refines="#creator" property="role" scheme="marc:relators">aut</meta>\n'
        if author else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id"'
        ' prefix="rendition: http://www.idpf.org/vocab/rendition/#">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="book-id">urn:uuid:{book_id}</dc:identifier>\n'
        f'    <dc:title>{_esc(title)}</dc:title>\n'
        + creator
        + '    <dc:language>fr</dc:language>\n'
        '    <meta property="rendition:layout">pre-paginated</meta>\n'
        '    <meta property="rendition:spread">both</meta>\n'
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        '  </metadata>\n'
        '  <manifest>\n' + "\n".join(manifest) + '\n  </manifest>\n'
        '  <spine>\n' + "\n".join(spine) + '\n  </spine>\n</package>\n'
    )


def _nav(title: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"'
        ' lang="fr"><head><meta charset="utf-8"/>'
        f'<title>{_esc(title)}</title></head>\n<body>\n'
        '  <nav epub:type="toc" id="toc"><ol>'
        f'<li><a href="titlepage.xhtml">{_esc(title)}</a></li></ol></nav>\n'
        '  <nav epub:type="landmarks" id="landmarks" hidden="">\n'
        '    <ol><li><a epub:type="titlepage" href="titlepage.xhtml">Page de titre</a></li>\n'
        '    <li><a epub:type="bodymatter" href="p0L.xhtml">Texte</a></li></ol>\n'
        '  </nav>\n</body></html>\n'
    )


def _assemble(title: str, author: str, spreads: list[dict], output_path: Path) -> None:
    """Zip the paginated spreads into a fixed-layout EPUB. Pure: no browser."""
    book_id = str(uuid.uuid4())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_name(output_path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        # The mimetype must be first and stored — the one part a reader may sniff
        # by byte offset.
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr("OEBPS/style.css", _stylesheet())
        z.writestr("OEBPS/paper.png", (ASSETS / "paper-grain.png").read_bytes())
        z.writestr("OEBPS/nav.xhtml", _nav(title))
        z.writestr("OEBPS/content.opf", _opf(title, book_id, author, len(spreads)))
        z.writestr("OEBPS/titlepage.xhtml", _titlepage_doc(title, author))
        for i, spread in enumerate(spreads):
            folio = i + 1
            z.writestr(f"OEBPS/p{i}L.xhtml",
                       _page_doc("page-left", _column_html(spread["fr"], "fr", spread["chapter"], folio)))
            z.writestr(f"OEBPS/p{i}R.xhtml",
                       _page_doc("page-right", _column_html(spread["en"], "en", spread["chapter"], folio)))
    tmp.replace(output_path)


CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def write_epub(
    title: str,
    chapters: list[Chapter],
    translations: dict[str, str],
    output_path: Path,
    target: Target = ENGLISH,
    author: str = "",
) -> None:
    pairs, chapter_meta = _book_pairs(chapters, translations, target)
    spreads = _paginate(pairs, chapter_meta, target.code)
    _assemble(title, author, spreads, output_path)
