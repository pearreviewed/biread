"""PDF -> text, via pypdf (pure Python). Imported lazily so the package still
loads where pypdf is absent — a browser build installs it on demand, only when a
PDF is actually dropped in.

A PDF made of scanned images carries no text to extract; that surfaces as a
clear error rather than an empty book. Real OCR is out of scope.
"""
from __future__ import annotations

from pathlib import Path

from ..errors import ExtractError
from .base import Extractor


class PdfExtractor(Extractor):
    suffixes = (".pdf",)

    def extract(self, path: Path) -> str:
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise ExtractError("reading PDFs needs the 'pypdf' package.") from e
        try:
            pages = [page.extract_text() or "" for page in PdfReader(str(path)).pages]
        except Exception as e:
            raise ExtractError(f"{path.name} could not be read as a PDF ({e}).") from e

        text = "\n\n".join(p.strip() for p in pages if p.strip())
        if not text:
            raise ExtractError(
                f"no selectable text in {path.name} — it may be scanned images "
                f"rather than text. An EPUB or TXT version will read far better."
            )
        return text
