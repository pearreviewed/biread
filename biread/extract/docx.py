"""DOCX -> text. A .docx is a zip; body text lives in word/document.xml as
<w:p> paragraphs of <w:t> runs.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from ..errors import ExtractError
from .base import Extractor

DOCUMENT = "word/document.xml"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocxExtractor(Extractor):
    suffixes = (".docx",)

    def extract(self, path: Path) -> str:
        try:
            with zipfile.ZipFile(path) as zf:
                xml = zf.read(DOCUMENT)
        except (zipfile.BadZipFile, KeyError) as e:
            raise ExtractError(f"{path.name} is not a readable .docx ({e}).") from e
        try:
            body = ET.fromstring(xml)
        except ET.ParseError as e:
            raise ExtractError(f"{path.name} has unreadable document XML ({e}).") from e

        paragraphs = ["".join(t.text or "" for t in p.iter(f"{W}t")) for p in body.iter(f"{W}p")]
        text = re.sub(r"\n{3,}", "\n\n", "\n\n".join(paragraphs)).strip()
        if not text:
            raise ExtractError(f"no readable text found in {path.name}.")
        return text
