"""What a file says about itself, before a word of it is read.

Only what is actually written in the file: an EPUB carries its title and author
in the OPF, a PDF knows how many pages it has, a text file knows nothing at all.
Nothing is inferred — a filename is not an author — so every field may be None,
and the caller shows what it has and stays quiet about the rest. A confident
wrong byline is worse than a blank one.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from .cleanup import Chapter
from .errors import ExtractError
from .extract.epub import opf_path


@dataclass
class BookInfo:
    title: str | None
    author: str | None
    language: str | None
    pages: int | None  # real pages, where the format has any
    paragraphs: int | None


def describe(path: Path, chapters: list[Chapter] | None = None) -> BookInfo:
    title = author = language = pages = None
    suffix = path.suffix.lower()
    if suffix == ".epub":
        title, author, language = _epub_metadata(path)
    elif suffix == ".pdf":
        pages = _pdf_pages(path)
    return BookInfo(
        title, author, language, pages,
        sum(len(c.paragraphs) for c in chapters) if chapters is not None else None,
    )


def _epub_metadata(path: Path) -> tuple[str | None, str | None, str | None]:
    """The OPF's Dublin Core title, creator and language.

    A metadata block that will not parse is not grounds to refuse the file: the
    extractor reads the same EPUB straight after and says so in its own words if
    it is truly unreadable. Here it is simply three things we do not know.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            opf = ET.fromstring(zf.read(opf_path(zf)))
    except (OSError, zipfile.BadZipFile, KeyError, ET.ParseError, ExtractError):
        return None, None, None

    def first(tag: str) -> str | None:
        element = opf.find(f".//{{*}}metadata/{{*}}{tag}")
        text = element.text.strip() if element is not None and element.text else ""
        return text or None

    return first("title"), first("creator"), first("language")


def _pdf_pages(path: Path) -> int | None:
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except Exception:  # pypdf absent, or the file is not a readable PDF
        return None
