"""HTML -> text. Also the text half of the EPUB extractor, whose chapters are
XHTML. Structure is left to cleanup.py; this only turns tags into the line and
paragraph breaks a .txt would carry.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from ..errors import ExtractError
from .base import Extractor

_SKIP = {"script", "style", "head", "title", "noscript"}
_BLOCK = {"p", "div", "li", "tr", "blockquote", "section", "article",
          "figcaption", "pre", "h1", "h2", "h3", "h4", "h5", "h6"}


class _ToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP:
            self._skip += 1
        elif tag == "br":
            self.parts.append("\n")

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag in _BLOCK:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _ToText()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class HtmlExtractor(Extractor):
    suffixes = (".html", ".htm")

    def extract(self, path: Path) -> str:
        raw = path.read_bytes()
        for encoding in ("utf-8-sig", "cp1252"):
            try:
                html = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ExtractError(f"could not decode {path.name} as UTF-8 or cp1252.")
        text = html_to_text(html)
        if not text:
            raise ExtractError(f"no readable text found in {path.name}.")
        return text
