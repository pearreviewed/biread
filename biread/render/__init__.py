"""Chapters + translations -> one self-contained HTML file.

The reader itself lives in templates/ as real .html/.css/.js. This module only
assembles them: inline the fonts and paper texture, serialise the book, and
write the result atomically.

Pagination happens in the browser, at runtime, against the real page box. A
paragraph taller than a page continues onto the next one, with both columns
broken at the same fraction through the paragraph so they meet again where it
ends — the prototype split at sentence level and matched sentence counts, which
real translations do not preserve.
"""
from __future__ import annotations

import base64
import json
import re
import unicodedata
from pathlib import Path

from ..cleanup import Chapter
from ..gloss import displayable
from ..targets import ENGLISH, Target
from ..translate import hash_text

TEMPLATES = Path(__file__).parent / "templates"
ASSETS = Path(__file__).parent.parent / "assets"

# Where a reader's own key would call, per provider, and which wire shape the
# reader uses. Embedded only by --revise, so a plain book carries no URL. The
# reader falls back to hand-editing when a provider has no browser endpoint.
REVISE_ENDPOINT = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "openai": "https://api.openai.com/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "ollama": "http://localhost:11434/api/chat",
}
REVISE_STYLE = {
    "anthropic": "anthropic",
    "openai": "openai",
    "openrouter": "openai",
    "ollama": "ollama",
}

PLACEHOLDER_RE = re.compile(r"@@([A-Z_]+)@@")

# Anything that could close the <script> element the book data lives in, plus
# the two line separators that are legal in JSON but not in JS string literals.
# Spelled as escapes on purpose: as literal characters they are invisible in an
# editor, and one stray keystroke would turn this into a space-mangling table.
JSON_ESCAPES = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
    "\u2028": "\\u2028",
    "\u2029": "\\u2029",
}


def fill(template: str, values: dict[str, str]) -> str:
    """Substitute @@NAME@@ placeholders in one pass.

    One pass matters: the book text is one of the values, and a sequential
    chain of str.replace would happily expand a placeholder that appeared
    inside a value substituted earlier.
    """
    def replace(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise KeyError(f"template references unknown placeholder @@{name}@@")
        return values[name]

    return PLACEHOLDER_RE.sub(replace, template)


def slugify(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_title).strip("-").lower() or "book"


#: Characters no filesystem or download will accept, plus control codes.
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def download_name(title: str) -> str:
    """The name the reader, EPUB and PDF are saved under: the title itself, kept
    readable — accents and spaces and all — with the illegal characters removed,
    then " - bilingual reader" so a download says what it is."""
    safe = _UNSAFE_FILENAME.sub("", title)
    safe = re.sub(r"\s+", " ", safe).strip().rstrip(".") or "book"
    return f"{safe} - bilingual reader"


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def script_json(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    for char, escape in JSON_ESCAPES.items():
        payload = payload.replace(char, escape)
    return payload


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


# A file the reader can download: (format id, saved filename, its bytes).
#: (format, source, filename, bytes). `source` is "translation" or "published":
#: a book built with a published translation carries both editions, and the
#: reader hands over whichever the reader has open.
Download = tuple[str, str, str, bytes]


def _download_scripts(downloads: list[Download] | None) -> str:
    """One base64 <script> blob per built edition, read only when the reader
    downloads it. Kept out of the book data so a multi-megabyte PDF is not parsed
    on every open. base64 has no `<`, so it cannot close the script early."""
    if not downloads:
        return ""
    return "\n".join(
        f'<script type="application/octet-stream" id="dl-{fmt}-{source}">'
        f'{base64.b64encode(blob).decode("ascii")}</script>'
        for fmt, source, _filename, blob in downloads
    )


def build_book_data(
    title: str,
    chapters: list[Chapter],
    translations: dict[str, str],
    published: dict[str, str] | None = None,
    published_note: str = "",
    glosses: dict | None = None,
    downloads: list[Download] | None = None,
    target: Target = ENGLISH,
    solo: bool = False,
    revise: dict | None = None,
    builder_url: str = "",
) -> dict:
    """`pairs` is a flat list of {fr, en} across the whole book, including any
    untitled leading section. `chapters[i].pair` indexes into it, marking where
    that chapter's body starts — the reader forces a page break there.

    `revise`, when set, turns on reader-side correction: each body pair carries
    its source hash `h` (so a reader's local fix survives a rebuild and goes
    stale safely if the paragraph is retranslated), and the reader learns which
    provider/model to call on the reader's own key."""
    pairs = []
    chapter_meta = []
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
            key = hash_text(paragraph)
            pair = {"fr": paragraph, "en": translations.get(key, "")}
            if revise:
                pair["h"] = key
            if published:
                pair["pub"] = published.get(key, "")
            units = displayable(paragraph, (glosses or {}).get(key) or [])
            if units:
                # Positional, to keep the payload small: a book carries tens of
                # thousands of these. [start, end, part of speech, gloss,
                # infinitive, passé composé] — the last two usually empty.
                pair["units"] = [
                    [u.start, u.end, u.pos, u.gloss, u.infinitive, u.perfect]
                    for u in units
                ]
            pairs.append(pair)

    data = {
        "titleFr": title,
        "slug": slugify(title),
        "publishedAvailable": bool(published),
        "publishedNote": published_note,
        "pairs": pairs,
        "chapters": chapter_meta,
        # The target language: `lang` drives the translated column's hyphenation,
        # `ui` carries every functional label the reader applies at boot.
        "lang": target.code,
        "ui": target.ui,
    }
    if downloads:
        # Just what the menu needs; the bytes ride in their own <script> blobs.
        data["downloads"] = [
            {"format": fmt, "source": source, "filename": filename}
            for fmt, source, filename, _blob in downloads
        ]
    if solo:
        # A brought translation set beside the French by position: the reader
        # shows it as one honest column, with no AI/published toggle.
        data["solo"] = True
    if revise:
        # No key and no cost live here — only which endpoint a reader's own key
        # would call, its wire shape, the model, and the prompt's target language.
        provider = revise["provider"]
        data["revise"] = {
            "enabled": True,
            "provider": provider,
            "model": revise["model"],
            "target": revise.get("target", target.name),
            "endpoint": REVISE_ENDPOINT.get(provider, ""),
            "style": REVISE_STYLE.get(provider, "openai"),
        }
    if builder_url:
        # Where this book's reader can cross to the builder. Set only when there
        # is somewhere real to go, so a book that travels never shows an arrow
        # into nothing — which is what made the old placeholder a dead end.
        data["builderUrl"] = builder_url
    return data


def render_html(
    title: str,
    chapters: list[Chapter],
    translations: dict[str, str],
    published: dict[str, str] | None = None,
    published_note: str = "",
    glosses: dict | None = None,
    downloads: list[Download] | None = None,
    target: Target = ENGLISH,
    solo: bool = False,
    revise: dict | None = None,
    builder_url: str = "",
) -> str:
    """The finished reader as a single HTML string. `render_book` writes it to a
    file; the in-browser builder hands the same string straight to a download."""
    data = build_book_data(
        title, chapters, translations, published, published_note, glosses, downloads,
        target, solo, revise, builder_url,
    )

    css = fill((TEMPLATES / "reader.css").read_text(encoding="utf-8"), {
        "FONT_REGULAR": _b64(ASSETS / "fonts" / "charis-sil-400.woff2"),
        "FONT_ITALIC": _b64(ASSETS / "fonts" / "charis-sil-400-italic.woff2"),
        "PAPER_GRAIN": _b64(ASSETS / "paper-grain.png"),
    })

    return fill((TEMPLATES / "reader.html").read_text(encoding="utf-8"), {
        "TITLE": escape_html(title),
        "CSS": css,
        "BOOK_DATA": script_json(data),
        "JS": (TEMPLATES / "reader.js").read_text(encoding="utf-8"),
        "DOWNLOADS": _download_scripts(downloads),
        "UI_LOADING": escape_html(target.ui["loading"]),
    })


def render_book(
    title: str,
    chapters: list[Chapter],
    translations: dict[str, str],
    output_path: Path,
    published: dict[str, str] | None = None,
    published_note: str = "",
    glosses: dict | None = None,
    downloads: list[Download] | None = None,
    target: Target = ENGLISH,
    revise: dict | None = None,
    builder_url: str = "",
) -> None:
    html = render_html(
        title, chapters, translations, published, published_note, glosses, downloads,
        target, revise=revise, builder_url=builder_url,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_name(output_path.name + ".tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(output_path)
