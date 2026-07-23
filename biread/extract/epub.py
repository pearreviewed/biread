"""EPUB -> text. An EPUB is a zip of XHTML documents; read them in spine order
and pull the text from each, reusing the HTML extractor.
"""
from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from urllib.parse import unquote
from xml.etree import ElementTree as ET

from ..errors import ExtractError
from .base import Extractor
from .html import html_to_text

CONTAINER = "META-INF/container.xml"


class EpubExtractor(Extractor):
    suffixes = (".epub",)

    def extract(self, path: Path) -> str:
        try:
            with zipfile.ZipFile(path) as zf:
                opf_path = self._opf_path(zf)
                text = self._spine_text(zf, opf_path)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as e:
            raise ExtractError(f"{path.name} is not a readable EPUB ({e}).") from e
        if not text.strip():
            raise ExtractError(f"no readable text found in {path.name}.")
        return text

    def _opf_path(self, zf: zipfile.ZipFile) -> str:
        rootfile = ET.fromstring(zf.read(CONTAINER)).find(".//{*}rootfile")
        full_path = rootfile.get("full-path") if rootfile is not None else None
        if not full_path:
            raise ExtractError("EPUB container names no rootfile.")
        return full_path

    def _spine_text(self, zf: zipfile.ZipFile, opf_path: str) -> str:
        opf = ET.fromstring(zf.read(opf_path))
        base = posixpath.dirname(opf_path)
        manifest = {
            item.get("id"): item.get("href")
            for item in opf.iterfind(".//{*}manifest/{*}item")
        }
        names = set(zf.namelist())
        parts = []
        for ref in opf.iterfind(".//{*}spine/{*}itemref"):
            href = manifest.get(ref.get("idref"))
            if not href:
                continue
            name = posixpath.normpath(posixpath.join(base, unquote(href.split("#")[0])))
            if name in names:
                parts.append(html_to_text(zf.read(name).decode("utf-8", "replace")))
        return "\n\n".join(p for p in parts if p)
