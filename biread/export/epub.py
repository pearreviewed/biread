"""A reflowable EPUB 3: the French and English interleaved, glosses as notes.

An e-reader paginates for itself, so there is no two-page spread to keep — each
French paragraph is followed by its English, the way parallel-text e-books have
always run. A glossed word becomes an EPUB footnote reference: readers that
support popups (Apple Books) reveal the gloss on a tap, and the rest fall back
to a note at the end of the chapter.

An EPUB is a ZIP with a fixed skeleton, so it is built here with the standard
library and nothing else.
"""
from __future__ import annotations

import uuid
import zipfile
from datetime import datetime, timezone
from itertools import count
from pathlib import Path

from ..cleanup import Chapter
from ..gloss import GlossUnit, displayable
from ..targets import ENGLISH, Target
from ..translate import hash_text

CONTAINER_XML = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

STYLESHEET = """\
body { font-family: Georgia, 'Times New Roman', serif; line-height: 1.5; margin: 1em; }
h2 { font-size: 1.3em; margin: 1.6em 0 0.2em; }
h2 .eyebrow { display: block; font-size: 0.6em; letter-spacing: 0.2em;
  text-transform: uppercase; color: #777; font-weight: normal; }
p.fr { margin: 1em 0 0.15em; }
p.en { margin: 0 0 1em; color: #444; font-style: italic; }
p.fr[lang="fr"] { hyphens: auto; }
a.gloss { text-decoration: none; border-bottom: 1px dotted #999; color: inherit; }
aside.note { font-size: 0.85em; color: #555; }
aside.note .pos { font-style: italic; color: #888; }
aside.note .form { color: #666; }
"""


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _french_html(paragraph: str, units: list[GlossUnit], ids) -> tuple[str, list[str]]:
    """The French paragraph with each gloss unit linked to a footnote.

    Returns the paragraph's inner HTML and the footnote <aside>s it refers to.
    """
    out: list[str] = []
    notes: list[str] = []
    cursor = 0
    for unit in units:
        if unit.start > cursor:
            out.append(_esc(paragraph[cursor:unit.start]))
        n = next(ids)
        note_id, ref_id = f"n{n}", f"r{n}"
        surface = _esc(paragraph[unit.start:unit.end])
        out.append(
            f'<a class="gloss" epub:type="noteref" href="#{note_id}" id="{ref_id}">{surface}</a>'
        )
        notes.append(_note_html(note_id, ref_id, unit))
        cursor = unit.end
    if cursor < len(paragraph):
        out.append(_esc(paragraph[cursor:]))
    return "".join(out), notes


def _note_html(note_id: str, ref_id: str, unit: GlossUnit) -> str:
    parts = [f'<span class="gloss-en">{_esc(unit.gloss)}</span>']
    if unit.pos:
        parts.append(f'<span class="pos"> ({_esc(unit.pos)})</span>')
    forms = []
    if unit.infinitive:
        forms.append("inf. " + _esc(unit.infinitive))
    if unit.perfect:
        forms.append("p.c. " + _esc(unit.perfect))
    if forms:
        parts.append(f'<span class="form"> — {"; ".join(forms)}</span>')
    return (f'<aside class="note" epub:type="footnote" id="{note_id}">'
            f'<p><a href="#{ref_id}">↩</a> {"".join(parts)}</p></aside>')


def _chapter_html(chapter: Chapter, translations, glosses, lang_code: str = "en") -> str:
    ids = count(1)
    body: list[str] = []
    notes: list[str] = []

    if chapter.title:
        eyebrow = f'<span class="eyebrow">Chapitre {_esc(chapter.number)}</span>' if chapter.number else ""
        body.append(f"<h2>{eyebrow}{_esc(chapter.title)}</h2>")

    for paragraph in chapter.paragraphs:
        key = hash_text(paragraph)
        units = displayable(paragraph, glosses.get(key, []))
        french, para_notes = _french_html(paragraph, units, ids)
        notes.extend(para_notes)
        body.append(f'<p class="fr" lang="fr">{french}</p>')
        english = translations.get(key, "")
        if english:
            body.append(f'<p class="en" lang="{lang_code}">{_esc(english)}</p>')

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" lang="fr">\n'
        f"<head><meta charset=\"utf-8\"/><title>{_esc(chapter.title or 'Chapitre')}</title>"
        '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
        "<body>\n" + "\n".join(body) + "\n"
        + ("<hr/>\n" + "\n".join(notes) + "\n" if notes else "")
        + "</body>\n</html>\n"
    )


def _nav_html(title: str, chapters: list[Chapter], files: list[str]) -> str:
    items = "\n".join(
        f'      <li><a href="{f}">{_esc(c.title or ("Chapitre " + (c.number or "")).strip())}</a></li>'
        for c, f in zip(chapters, files)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="fr">\n'
        f"<head><meta charset=\"utf-8\"/><title>{_esc(title)}</title></head>\n"
        '<body>\n  <nav epub:type="toc" id="toc">\n    <h1>Sommaire</h1>\n    <ol>\n'
        f"{items}\n    </ol>\n  </nav>\n</body>\n</html>\n"
    )


def _opf(title: str, book_id: str, files: list[str], lang_code: str = "en") -> str:
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = [
        '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '    <item id="css" href="style.css" media-type="text/css"/>',
    ]
    spine = []
    for i, f in enumerate(files):
        manifest.append(f'    <item id="ch{i}" href="{f}" media-type="application/xhtml+xml"/>')
        spine.append(f'    <itemref idref="ch{i}"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'    <dc:identifier id="book-id">urn:uuid:{book_id}</dc:identifier>\n'
        f"    <dc:title>{_esc(title)}</dc:title>\n"
        "    <dc:language>fr</dc:language>\n"
        f"    <dc:language>{lang_code}</dc:language>\n"
        f'    <meta property="dcterms:modified">{modified}</meta>\n'
        "  </metadata>\n"
        "  <manifest>\n" + "\n".join(manifest) + "\n  </manifest>\n"
        '  <spine>\n' + "\n".join(spine) + "\n  </spine>\n"
        "</package>\n"
    )


def write_epub(
    title: str,
    chapters: list[Chapter],
    translations: dict[str, str],
    glosses: dict[str, list[GlossUnit]] | None,
    output_path: Path,
    target: Target = ENGLISH,
) -> None:
    glosses = glosses or {}
    files = [f"chapter{i}.xhtml" for i in range(len(chapters))]
    book_id = str(uuid.uuid4())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_name(output_path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        # The mimetype must be first and stored, not compressed — the one part of
        # the archive a reader may sniff by byte offset.
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr("OEBPS/style.css", STYLESHEET)
        z.writestr("OEBPS/nav.xhtml", _nav_html(title, chapters, files))
        z.writestr("OEBPS/content.opf", _opf(title, book_id, files, target.code))
        for chapter, name in zip(chapters, files):
            z.writestr(f"OEBPS/{name}", _chapter_html(chapter, translations, glosses, target.code))
    tmp.replace(output_path)
