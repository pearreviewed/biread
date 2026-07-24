"""The extractor interface: source file -> raw text. Nothing more.

An extractor turns whatever format a book arrives in into a plain string. It
must not strip boilerplate, join wrapped lines, or detect chapters — that is
cleanup.py's job, and keeping the two apart is what lets a new format drop in
as one new file with no changes downstream.
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Optional

#: Reports reading progress: on_page(done, total). Only a paged format (a PDF)
#: has anything to report; the rest read in one step and leave it unused. A slow
#: read is otherwise a silent wait, and a PDF read glyph by glyph is slow.
PageProgress = Callable[[int, int], None]


class Extractor(ABC):
    #: File suffixes this extractor claims, lowercase and dotted.
    suffixes: tuple[str, ...] = ()

    @classmethod
    def handles(cls, path: Path) -> bool:
        return path.suffix.lower() in cls.suffixes

    @abstractmethod
    def extract(self, path: Path, on_page: Optional[PageProgress] = None) -> str:
        """Return the raw text content of the file at `path`.

        `on_page`, when given, is called as pages are read; a format without
        pages ignores it."""
