"""PDF -> text, via pypdf (pure Python). Imported lazily so the package still
loads where pypdf is absent — a browser build installs it on demand, only when a
PDF is actually dropped in.

Extraction is in layout mode, which rebuilds each line from the glyphs' own
positions. The default mode guesses word breaks from the gap between glyphs and
gets them wrong on tight kerning — "il fallait" comes out "il f allait", "les
cochons" as "l es cochons" — and runs paragraphs together; layout mode keeps
words whole and the blank line between paragraphs intact. It is several times
slower, which only PDFs pay, and an EPUB or TXT edition sidesteps it entirely.

A PDF made of scanned images carries no text to extract; that surfaces as a
clear error rather than an empty book. Real OCR is out of scope.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..errors import ExtractError
from .base import Extractor, PageProgress


def _page_text(page) -> str:
    """A page in layout mode, falling back to the default if it cannot lay one
    out — a rare malformed page should not lose the whole book."""
    try:
        return page.extract_text(extraction_mode="layout") or ""
    except Exception:
        return page.extract_text() or ""


class PdfExtractor(Extractor):
    suffixes = (".pdf",)

    def extract(self, path: Path, on_page: Optional[PageProgress] = None) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise ExtractError("reading PDFs needs the 'pypdf' package.") from e
        try:
            book_pages = PdfReader(str(path)).pages
            total = len(book_pages)
            pages = []
            for index, page in enumerate(book_pages, 1):
                pages.append(_page_text(page))
                if on_page:
                    on_page(index, total)
        except Exception as e:
            raise ExtractError(f"{path.name} could not be read as a PDF ({e}).") from e

        text = "\n\n".join(p.strip() for p in pages if p.strip())
        if not text:
            raise ExtractError(
                f"no selectable text in {path.name} — it may be scanned images "
                f"rather than text. An EPUB or TXT version will read far better."
            )
        return text
