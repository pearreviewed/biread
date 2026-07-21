"""A print PDF: the French and English side by side, no glosses.

The reader's whole point is runtime pagination and hover; a printed page keeps
neither. What it keeps is the parallel layout — French in the left column,
English in the right, aligned paragraph by paragraph — which is how bilingual
editions have been set for centuries. Glosses are left out on purpose: footnotes
for every hover would bury the text.

The page is laid out as HTML and printed by headless Chromium, so the type
matches the reader exactly. That engine is the one real cost — PDF export needs
the `[browser]` extra (`pip install -e ".[browser]"` and `playwright install
chromium`); EPUB does not, which is why the import is deferred to here.
"""
from __future__ import annotations

import base64
from pathlib import Path

from ..cleanup import Chapter
from ..errors import BireadError
from ..translate import hash_text

ASSETS = Path(__file__).parent.parent / "assets"


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _print_html(title: str, chapters: list[Chapter], translations: dict[str, str]) -> str:
    regular = _b64(ASSETS / "fonts" / "eb-garamond-400.woff2")
    italic = _b64(ASSETS / "fonts" / "eb-garamond-400-italic.woff2")

    rows: list[str] = []
    for chapter in chapters:
        if chapter.title:
            eyebrow = f"Chapitre {_esc(chapter.number)}" if chapter.number else ""
            rows.append(
                f'<tr><td class="head" colspan="2">'
                f'<div class="eyebrow">{eyebrow}</div><h2>{_esc(chapter.title)}</h2></td></tr>'
            )
        for paragraph in chapter.paragraphs:
            english = translations.get(hash_text(paragraph), "")
            rows.append(
                '<tr>'
                f'<td class="fr" lang="fr">{_esc(paragraph)}</td>'
                f'<td class="en" lang="en">{_esc(english)}</td>'
                '</tr>'
            )

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>{_esc(title)}</title>
<style>
@font-face {{ font-family: 'EB Garamond'; font-style: normal; font-weight: 400;
  src: url(data:font/woff2;base64,{regular}) format('woff2'); }}
@font-face {{ font-family: 'EB Garamond'; font-style: italic; font-weight: 400;
  src: url(data:font/woff2;base64,{italic}) format('woff2'); }}
* {{ box-sizing: border-box; }}
body {{ font-family: 'EB Garamond', Georgia, serif; font-size: 10.5pt; line-height: 1.42;
  color: #201a12; background: #fff; margin: 0; }}
h1.book {{ text-align: center; font-size: 22pt; margin: 0 0 4pt; }}
.byline {{ text-align: center; color: #8a7551; letter-spacing: .18em;
  text-transform: uppercase; font-size: 8pt; margin-bottom: 20pt; }}
table {{ width: 100%; border-collapse: collapse; }}
td {{ width: 50%; vertical-align: top; padding: 0 14pt 9pt; text-align: justify;
  hyphens: auto; }}
td.fr {{ border-right: .5pt solid #d8cdb6; }}
td.en {{ font-style: italic; color: #453f34; }}
tr {{ break-inside: auto; }}
td.head {{ padding-top: 16pt; }}
td.head:first-child, td.head {{ border-right: none; text-align: left; }}
.eyebrow {{ font-size: 7.5pt; letter-spacing: .28em; text-transform: uppercase;
  color: #8a7551; }}
h2 {{ font-size: 14pt; margin: 2pt 0 8pt; break-after: avoid; }}
</style></head>
<body>
<h1 class="book">{_esc(title)}</h1>
<div class="byline">Lecteur bilingue</div>
<table>
{chr(10).join(rows)}
</table>
</body></html>
"""


def write_pdf(
    title: str,
    chapters: list[Chapter],
    translations: dict[str, str],
    output_path: Path,
) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise BireadError(
            "PDF export needs the browser engine. Install it with:\n"
            '  pip install -e ".[browser]" && playwright install chromium'
        ) from e

    html = _print_html(title, chapters, translations)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.emulate_media(media="print", color_scheme="light")
                page.set_content(html, wait_until="load")
                page.evaluate("() => document.fonts.ready")  # embed the type before printing
                page.pdf(
                    path=str(output_path), format="A4", print_background=True,
                    margin={"top": "1.7cm", "bottom": "1.7cm", "left": "1.4cm", "right": "1.4cm"},
                )
            finally:
                browser.close()
    except BireadError:
        raise
    except Exception as e:
        raise BireadError(
            f"PDF export failed while rendering: {e}\n"
            "If this is the first run, the browser may be missing: playwright install chromium"
        ) from e
