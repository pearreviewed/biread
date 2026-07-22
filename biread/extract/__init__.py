from pathlib import Path

from ..errors import ExtractError
from .base import Extractor
from .docx import DocxExtractor
from .epub import EpubExtractor
from .html import HtmlExtractor
from .pdf import PdfExtractor
from .txt import TxtExtractor

# Adding a format = add a module and register its class here. Nothing else changes.
EXTRACTORS: tuple[type[Extractor], ...] = (
    TxtExtractor, HtmlExtractor, EpubExtractor, DocxExtractor, PdfExtractor,
)

__all__ = [
    "Extractor", "TxtExtractor", "HtmlExtractor", "EpubExtractor",
    "DocxExtractor", "PdfExtractor", "get_extractor",
]


def get_extractor(path: Path) -> Extractor:
    for cls in EXTRACTORS:
        if cls.handles(path):
            return cls()
    supported = ", ".join(sorted(s for cls in EXTRACTORS for s in cls.suffixes))
    suffix = path.suffix.lower() or "(no extension)"
    raise ExtractError(
        f"no extractor for {suffix} files: {path.name}. Supported: {supported}."
    )
