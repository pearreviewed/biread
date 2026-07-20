"""The extractor interface: source file -> raw text. Nothing more.

An extractor turns whatever format a book arrives in into a plain string. It
must not strip boilerplate, join wrapped lines, or detect chapters — that is
cleanup.py's job, and keeping the two apart is what lets a new format drop in
as one new file with no changes downstream.
"""
from abc import ABC, abstractmethod
from pathlib import Path


class Extractor(ABC):
    #: File suffixes this extractor claims, lowercase and dotted.
    suffixes: tuple[str, ...] = ()

    @classmethod
    def handles(cls, path: Path) -> bool:
        return path.suffix.lower() in cls.suffixes

    @abstractmethod
    def extract(self, path: Path) -> str:
        """Return the raw text content of the file at `path`."""
