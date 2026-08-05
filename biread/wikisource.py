"""Find and fetch a book's two editions on Wikisource.

Given nothing but a page name, this walks the work to its chapters and reads
them into biread Chapters. Wikisource marks its own apparatus — navigation
headers, page-scan numbers, licence boxes — with `ws-noexport` / `noprint`, so
the body is what is left once those are dropped. That is the site's semantics,
not a per-book rule, which is what lets one resolver carry every book.

Nothing here opens a socket by itself. Every entry point takes a `fetch`, so the
same code reads through `requests` on the command line and through the browser's
own fetch inside Pyodide, where there is no socket to open.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable

from biread.cleanup import Chapter
from biread.numbering import chapter_number

REST = "https://{lang}.wikisource.org/api/rest_v1/page/html/{title}"
API = "https://{lang}.wikisource.org/w/api.php"
UA = "biread/0.1 (https://github.com/pearreviewed/biread)"

Fetch = Callable[[str], str]

# Not the book: apparatus Wikisource itself flags. Footnote markers are <sup>
# too, but so is the "lle" of Mlle — they are told apart by class, not by tag.
_SKIP_TAGS = {"script", "style", "table", "head", "figure"}
_SKIP_CLASSES = ("ws-noexport", "noprint", "pagenum", "reference", "mw-editsection")
_VOID = {"br", "img", "link", "meta", "hr", "input", "source", "area", "col"}


def page_url(lang: str, title: str) -> str:
    return REST.format(lang=lang, title=urllib.parse.quote(title.replace(" ", "_"), safe=""))


def query_url(lang: str, **params: str) -> str:
    params = {"format": "json", "formatversion": "2", "origin": "*", **params}
    return API.format(lang=lang) + "?" + urllib.parse.urlencode(params)


def default_fetch(url: str) -> str:
    """Read a URL over the network. Not used in the browser, which brings its own."""
    import requests  # not installed in Pyodide, where fetch is injected instead

    r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    return r.text


def _unquote(href: str) -> str:
    return urllib.parse.unquote(href[2:] if href.startswith("./") else href).replace("_", " ")


class _Links(HTMLParser):
    """Every internal link, in document order — a work's index lists its parts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href", "")
        # A page that does not exist is linked with an edit query on the end.
        # It is offered as a choice like any other and leads nowhere.
        if href.startswith("./") and "?" not in href and ":" not in href.split("/")[-1]:
            page = _unquote(href)
            if page not in self.hrefs:
                self.hrefs.append(page)


class _Body(HTMLParser):
    """Paragraphs of the work itself, and the chapter title from the header."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self.title: str | None = None
        #: Indices of paragraphs the edition set centred — display matter by the
        #: wiki's own account, which is what tells a heading from a first line.
        self.centred: set[int] = set()
        self._stack: list[tuple[bool, bool, bool]] = []   # skips, drop cap, centred
        self._skip = 0
        self._drop = 0
        self._centre = 0
        self._buf: list[str] | None = None
        self._title_buf: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _VOID:
            # A line break separates words as surely as a space does, and dropping
            # it outright ran them together: this edition's chapter headings came
            # out as "CHAPTER VIIIMOBILIS IN MOBILI". Verse and addresses break
            # the same way wherever an edition sets them with <br>.
            if tag == "br":
                for buf in (self._buf, self._title_buf):
                    if buf is not None:
                        buf.append(" ")
            # Some editions set the drop cap as a scan of the printed initial
            # rather than as a letter. Twenty Thousand Leagues opens every one of
            # its 46 chapters that way, and each opened on a beheaded word —
            # "HE year 1866", "E now come to the second part". The alt text is
            # the wiki naming the letter itself, so it is read, not guessed; and
            # only inside a drop cap, because elsewhere an alt describes a
            # picture and is not part of the prose.
            elif tag == "img" and self._drop and self._buf is not None:
                self._buf.append(dict(attrs).get("alt", ""))
            return
        classes = dict(attrs).get("class", "")
        skips = tag in _SKIP_TAGS or any(c in classes for c in _SKIP_CLASSES)
        # The title lives inside the header, which is itself dropped.
        if "wst-header-title-text" in classes:
            self._title_buf = []
        # A drop cap is a big first letter, and the wiki puts the space *inside*
        # it — `<span class="dropinitial">N </span><span class="sc">ous</span>`.
        # Rendered that space is nothing, because the span floats; read as text
        # it splits the first word of a chapter, which is the most looked-at
        # word in the book. Madame Bovary opened on "N ous étions à l'étude".
        drop = "dropinitial" in classes
        centre = "wst-center" in classes
        self._stack.append((skips, drop, centre))
        if skips:
            self._skip += 1
        else:
            if drop:
                self._drop += 1
            if centre:
                self._centre += 1
            if tag == "p" and self._buf is None:
                self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID or not self._stack:
            return
        if tag == "p" and self._buf is not None:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if len(text) > 20:
                if self._centre:
                    self.centred.add(len(self.paragraphs))
                self.paragraphs.append(text)
            self._buf = None
        if self._title_buf is not None and not self.title:
            text = re.sub(r"\s+", " ", "".join(self._title_buf)).strip()
            if text:
                self.title = text
                self._title_buf = None
        skipped, drop, centre = self._stack.pop()
        if skipped:
            self._skip -= 1
        else:
            if drop:
                self._drop -= 1
            if centre:
                self._centre -= 1

    def handle_data(self, data: str) -> None:
        if self._title_buf is not None:
            self._title_buf.append(data)
        if self._skip:
            return
        if self._buf is not None:
            self._buf.append(data.strip() if self._drop else data)


# French runs a dialogue inside one paragraph, each new speaker opened by an
# em dash; English translations give every speech its own paragraph. Split on
# the dash only where a sentence has just closed, so a parenthetical dash mid
# sentence is left alone — and so an edition that already breaks its speeches
# out is left alone too, its dashes being at the start of a paragraph with no
# sentence in front of them.
_SPEECH = re.compile(r"(?<=[.!?;…»\"])\s+[—–]\s+")

# Where dialogue is dashed rather than quoted. A property of the language, not
# of the book: every French edition tested fuses speeches this way.
DASH_DIALOGUE = {"fr", "es", "it", "pt", "ru", "uk", "pl", "ro", "no", "tr"}

# Not the work: colophons, transcriber's notes, licences. Checked only against
# the outermost paragraphs of a book, never against its body.
_APPARATUS = re.compile(
    r"this edition of|limited to \w+ copies|printed and bound|set in \w+ type"
    r"|transcriber'?s note|project gutenberg|is in the public domain"
    r"|typeset|colophon|all rights reserved|first published in",
    re.I,
)


def split_speeches(paragraph: str) -> list[str]:
    parts = [p.strip() for p in _SPEECH.split(paragraph)]
    return [p for p in parts if p]


def is_apparatus(text: str) -> bool:
    return bool(_APPARATUS.search(text))


def trim_apparatus(chapters: list[dict]) -> tuple[list[dict], list[str]]:
    """Drop production notes from the two ends of a book, and say what went."""
    removed = []
    for chapter, edge in ((chapters[0], 0), (chapters[-1], -1)):
        paras = chapter["paragraphs"]
        while paras and is_apparatus(paras[edge]):
            removed.append(paras.pop(edge))
    return chapters, removed


# The navigation header names the page it is on. That is the chapter's real
# title, and the only authority for whether the first body paragraph is a
# heading repeated in the text or the opening of the chapter itself.
_CURRENT = re.compile(r'"current":\{"wt":"(?:\[\[[^|\]]*\|)?(.*?)\]?\]?"\}')
# Wikitext the header carries around a title: {{sc|Première partie}} is small
# caps asking to be printed, not part of the name.
_TEMPLATE = re.compile(r"\{\{\s*\w+\s*\|([^{}|]*)\}\}")


def _plain(wikitext: str) -> str:
    """A header field as prose: templates unwrapped, markup and links dropped."""
    text = html.unescape(html.unescape(wikitext))
    for _ in range(3):
        text, n = _TEMPLATE.subn(r"\1", text)
        if not n:
            break
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"<[^>]*>", "", text).replace("\\", "").replace("'''", "")
    return re.sub(r"\s+", " ", text).strip(" .,")


# A heading set as an ordinary paragraph, with the chapter's title on the same
# line: "CHAPTER XIII THE BLACK RIVER". Roman and arabic numbers only, unlike
# cleanup.CHAPTER_RE — an edition that spells the number out sets it on a line of
# its own, and allowing a bare word here would read the first word of a title as
# the number.
_HEADING_PARA = re.compile(
    r"^(?:CHAPITRE|CHAPTER)\s+(?:[IVXLCDM]+|\d+)\s*[.—–-]?\s*(?P<title>.{0,160})$",
    re.IGNORECASE,
)

#: How far into a chapter the heading may be looked for, counted in centred
#: paragraphs. Enough for a volume title and a part number standing above it.
_LEADING_CENTRED = 3


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _same_heading(a: str, b: str) -> bool:
    """Two spellings of one title — editions differ in commas and stray words."""
    x, y = _norm(a), _norm(b)
    if not x or not y:
        return False
    shared = 0
    for ca, cb in zip(x, y):
        if ca != cb:
            break
        shared += 1
    return shared >= 0.6 * min(len(x), len(y))


# A header that carries only the chapter's number is a label, not a title; the
# reader prints its own "Chapitre I" eyebrow and does not want it twice.
_NUMBER_ONLY = re.compile(r"^(chap(itre|ter)?\.?\s*)?[ivxlcdm\d]+\.?$", re.I)


def header_title(page_html: str) -> str | None:
    m = _CURRENT.search(page_html)
    if not m:
        return None
    text = _plain(m.group(1))
    if not text or _NUMBER_ONLY.match(text):
        return None
    return text


# The header block names the edition: its title, its author, who translated it
# and when. Read, never guessed — a shelf entry claims only what the page says,
# and a book whose translator the wiki does not name is shown without one.
#
# Each wiki writes the field names in its own language: fr.wikisource's header
# says `auteur` where en.wikisource says `author`, so looking for one spelling
# only reads the author off half the library — and the French half is the half
# every original comes from.
_FIELD = r'"{field}":\s*\{{"wt":"(.*?)"\}}'
_FIELD_NAMES = {
    "title": ("title", "titre"),
    "author": ("author", "auteur"),
    "translator": ("translator", "traducteur"),
    "year": ("year", "annee", "année"),
}


@dataclass(frozen=True)
class Credits:
    title: str | None = None
    author: str | None = None
    translator: str | None = None
    year: str | None = None

    @property
    def edition(self) -> str | None:
        """How a card names the translation: who, and of when."""
        bits = [b for b in (surname(self.translator), self.year) if b]
        return " · ".join(bits) or None


def credits(page_html: str) -> Credits:
    got = {}
    for field_, names in _FIELD_NAMES.items():
        value = ""
        for name in names:
            m = re.search(_FIELD.format(field=name), page_html)
            value = _plain(m.group(1)) if m else ""
            if value:
                break
        got[field_] = value or None
    return Credits(**got)


def surname(name: str | None) -> str | None:
    """"Eleanor Marx-Aveling" -> "Marx-Aveling". A card has room for one word."""
    if not name:
        return None
    parts = name.split()
    return parts[-1] if parts else None


def parse(page_html: str, split_dialogue: bool = False) -> tuple[str | None, list[str]]:
    p = _Body()
    p.feed(page_html)
    paras = p.paragraphs
    title = header_title(page_html)
    # Some editions print the chapter title again at the top of the body.
    if title and paras and _same_heading(paras[0], title):
        paras = paras[1:]
    # And some set the heading as an ordinary centred paragraph, with no header
    # to name it: every chapter of Twenty Thousand Leagues opened on a body
    # paragraph reading "CHAPTER XIII THE BLACK RIVER". Lifted out and kept as
    # the title, so it reads as a heading and stops being matched as prose.
    #
    # Centred *and* heading-shaped, never shape alone. The edition setting it
    # centred is the wiki saying this is display matter; without that, a first
    # sentence opening "Chapter XI was the best of them" would be read as a
    # title, and a heading is not worth guessing at.
    elif not title and paras:
        # Anywhere in the leading run of centred matter, not only at the top:
        # chapter one of Twenty Thousand Leagues prints the volume's title above
        # its heading, and requiring the very first paragraph left that one
        # chapter — the one everybody opens — with its heading still in the body.
        for i, para in enumerate(paras[:_LEADING_CENTRED]):
            if i not in p.centred:
                break
            heading = _HEADING_PARA.match(para)
            if heading:
                title = heading.group("title").strip() or None
                paras = paras[:i] + paras[i + 1:]
                break
    if split_dialogue:
        paras = [s for para in paras for s in split_speeches(para)]
    return title, paras


# --- finding the chapters ---------------------------------------------------
#
# A work's page is one of four shapes, and only the first is the easy one:
#
#   chapters      Candide/Chapter 1 …                     leaves, numbered
#   editions      Candide, ou l'Optimisme/Garnier 1877/…  descend one level
#   translations  "English-language translations of …"    follow to a translation
#   single        the work sits on one page               no subpages at all
#
# What tells a chapter from apparatus is that a chapter's last path segment is a
# number. That drops /Audio, /Texte entier, and Madame Bovary's appended trial
# transcript without naming any of them.

# "English-language translations of Madame Bovary include:"
_HUB = re.compile(r"translations? of .+ includ", re.I)
_LEAD = re.compile(r"^(chap(itre|ter)?|part(ie)?|livre|book|tome)\.?\s*", re.I)

# Page names the wiki reuses across books for things that are not the work:
# the whole text on one page, a recording, a contents list, editorial matter.
_APPARATUS_PAGE = re.compile(
    r"^(texte entier|text|audio|table des matières|tables?|sommaire|contents"
    r"|notes?|préface|preface|avant-propos|introduction|appendice|appendix"
    r"|bibliographie|index|couverture|cover|title ?page|frontispice)$", re.I)


def numbered(page: str) -> int | None:
    """The chapter number a page title ends in, if it ends in one at all."""
    tail = page.rsplit("/", 1)[-1]
    return chapter_number(_LEAD.sub("", tail).strip(" .:"))


def is_apparatus_page(page: str) -> bool:
    return bool(_APPARATUS_PAGE.match(page.rsplit("/", 1)[-1].strip()))


def is_hub(paragraphs: list[str]) -> bool:
    return bool(paragraphs) and any(_HUB.search(p) for p in paragraphs[:3])


@dataclass
class Resolved:
    work: str
    pages: list[str]
    shape: str
    choices: list[str] = field(default_factory=list)
    # The page the chapters were found under, kept so an edition can be credited
    # from the page that actually holds it without asking the wiki twice.
    html: str = ""


def resolve(lang: str, work: str, fetch: Fetch = default_fetch, depth: int = 0) -> Resolved:
    """Where this work's chapters actually live, whatever shape its page is."""
    page = fetch(page_url(lang, work))
    _, paragraphs = parse(page)
    links = _Links()
    links.feed(page)
    subs = [h for h in links.hrefs if h.startswith(work + "/")]

    chapters = [s for s in subs if numbered(s) is not None]
    if chapters:
        return Resolved(work, chapters, "chapters", html=page)

    # Some works title their chapters instead of numbering them (Salammbô's
    # "Le Festin", "Tanit"). Then the only thing separating a chapter from
    # apparatus is that apparatus has a name the wiki reuses across books.
    named = [s for s in subs if not is_apparatus_page(s)]
    if len(named) >= 3:
        return Resolved(work, named, "named", html=page)

    # A hub lists other works, not subpages: follow one of them.
    if is_hub(paragraphs) and depth < 2:
        others = [h for h in links.hrefs if not h.startswith(work + "/")]
        if others:
            inner = resolve(lang, others[0], fetch, depth + 1)
            return Resolved(inner.work, inner.pages, "translation", others, inner.html)

    # Editions or parts: descend into whichever branch holds the most chapters.
    if subs and depth < 2:
        best = Resolved(work, [], "unresolved", subs)
        for sub in subs[:6]:
            try:
                got = resolve(lang, sub, fetch, depth + 1)
            except Exception:
                continue
            if len(got.pages) > len(best.pages):
                best = Resolved(got.work, got.pages, "edition", subs, got.html)
        if best.pages:
            return best

    if paragraphs:
        return Resolved(work, [work], "single", html=page)

    # No subpages, no text: a landing page whose editions sit beside it rather
    # than beneath it — "Le Père Goriot" listing "Le Père Goriot (1855)". They
    # are told apart from every other link by carrying the work's own name.
    siblings = [h for h in links.hrefs if h != work and h.startswith(work)]
    if siblings and depth < 2:
        best = Resolved(work, [], "unresolved", siblings)
        for sibling in siblings[:3]:
            try:
                got = resolve(lang, sibling, fetch, depth + 1)
            except Exception:
                continue
            if len(got.pages) > len(best.pages):
                best = Resolved(got.work, got.pages, "edition", siblings, got.html)
        if best.pages:
            return best

    return Resolved(work, [], "unresolved", subs, html=page)


# --- reading an edition ------------------------------------------------------

@dataclass(frozen=True)
class Edition:
    lang: str
    work: str          # the page a reader would land on
    resolved: str      # the page the chapters actually live under
    shape: str
    chapters: list[dict]
    credits: Credits = Credits()
    dropped: list[str] = field(default_factory=list)

    @property
    def paragraphs(self) -> int:
        return sum(len(c["paragraphs"]) for c in self.chapters)

    @property
    def chars(self) -> int:
        return sum(len(p) for c in self.chapters for p in c["paragraphs"])


def fetch_pages(lang: str, pages: list[str], fetch: Fetch = default_fetch,
                on_progress=None) -> tuple[list[dict], list[str]]:
    """Fetch resolved chapter pages. Nothing here is per-book."""
    out: list[dict] = []
    for i, page in enumerate(pages, 1):
        heading, paras = parse(fetch(page_url(lang, page)),
                               split_dialogue=lang in DASH_DIALOGUE)
        if paras:
            out.append({"number": str(len(out) + 1), "title": heading,
                        "page": page, "paragraphs": paras})
        if on_progress:
            on_progress(i, len(pages))
    if not out:
        return out, []
    return trim_apparatus(out)


def load(lang: str, work: str, fetch: Fetch = default_fetch, on_progress=None,
         skip: tuple[str, ...] = ()) -> Edition:
    """A whole edition, found and fetched, with nothing said about the book.

    `skip` names sections of the work's own page that are not the work — the
    wiki's Salammbô carries a Notice, its sources, 626 paragraphs of Variantes
    and the letters Flaubert received, all under names of their own and all
    calling themselves "book" in the header, so nothing on the page tells them
    from a chapter. Named by hand on the shelf record, because on a curated
    shelf a person has looked; a rule that dropped a trailing run of unmatched
    sections would also drop the last chapters of a translation that stops
    early, and losing those silently is the worse failure.
    """
    r = resolve(lang, work, fetch)
    if not r.pages:
        raise LookupError(f"no chapters found under {work!r} on {lang}.wikisource.org")
    pages = [p for p in r.pages if p.rsplit("/", 1)[-1] not in skip]
    if skip and len(pages) == len(r.pages):
        raise LookupError(
            f"{work!r}: none of the sections named in `skip` is there — "
            f"{skip}. The wiki has been renamed under us, or the list is stale.")
    chapters, dropped = fetch_pages(lang, pages, fetch, on_progress)
    if not chapters:
        raise LookupError(f"{work!r} resolved to {len(pages)} pages, none of them text")
    # A volume that prints its own title over chapter one — Twenty Thousand
    # Leagues opened on "Twenty Thousand Leagues Under the Sea." as a paragraph
    # of the book. Removed only where it repeats the name of the page we asked
    # for, so it is the edition agreeing with itself rather than a running head
    # recognised by its shape.
    first = chapters[0]["paragraphs"]
    if len(first) > 1 and _same_heading(first[0], work.rsplit("/", 1)[-1]):
        dropped = [*dropped, first.pop(0)]
    under = r.pages[0].rsplit("/", 1)[0] if r.shape != "single" else r.pages[0]
    return Edition(lang, work, under, r.shape, chapters, credits(r.html), dropped)


def to_chapters(edition: Edition) -> list[Chapter]:
    return [Chapter(number=c["number"], title=c["title"], paragraphs=c["paragraphs"])
            for c in edition.chapters]


# --- looking a book up -------------------------------------------------------

@dataclass(frozen=True)
class Hit:
    """A search result, and the counterpart edition it does or does not have."""
    title: str
    lang: str
    snippet: str
    counterpart: str | None = None      # the page name on the other Wikisource


@dataclass(frozen=True)
class Results:
    """One page of works, and how many more were seen behind it.

    `more` is a floor, never a total: it counts the whole works in the rows this
    search actually read, so it can only understate. Wikisource's own
    `totalhits` is no use here — it counts every chapter page, and forty
    chapters of Germinal are not forty books.
    """
    hits: list[Hit]
    more: int


_TAGS = re.compile(r"<[^>]+>")


def search(query: str, lang: str = "fr", limit: int = 6, offset: int = 0,
           fetch: Fetch = default_fetch) -> Results:
    """Works on one Wikisource matching a query, `limit` at a time.

    Only whole works: the search index holds every chapter page too, and three
    chapters of Germinal are not three books. A work is a page with nothing
    above it in the path.

    Paged on the works rather than on the rows, because the wiki numbers its
    rows and we are counting something else. Every page re-reads from the top —
    the filtering is ours, so only we know where work number five began.
    """
    import json

    url = query_url(lang, action="query", list="search", srsearch=query,
                    srlimit=str((offset + limit) * 5), srnamespace="0")
    data = json.loads(fetch(url))
    works = []
    for row in data.get("query", {}).get("search", []):
        if "/" in row["title"]:
            continue
        snippet = html.unescape(_TAGS.sub("", row.get("snippet", ""))).strip()
        works.append(Hit(row["title"], lang, re.sub(r"\s+", " ", snippet)))
    return Results(works[offset:offset + limit], max(0, len(works) - offset - limit))


def counterparts(titles: list[str], lang: str = "fr", other: str = "en",
                 fetch: Fetch = default_fetch) -> dict[str, str | None]:
    """The page each title has on the other Wikisource, by the wiki's own links.

    One call for the whole batch, and it is the wiki's answer rather than a guess
    at a translated title: a work with no free English edition comes back with
    nothing, which is the honest miss the lookup screen is built around.
    """
    import json

    if not titles:
        return {}
    url = query_url(lang, action="query", prop="langlinks", lllang=other,
                    lllimit="500", titles="|".join(titles))
    data = json.loads(fetch(url))
    found: dict[str, str | None] = {t: None for t in titles}
    for page in data.get("query", {}).get("pages", []):
        links = page.get("langlinks") or []
        found[page.get("title", "")] = links[0]["title"] if links else None
    return found
