"""Static exports of a book: EPUB for e-readers, PDF for print.

Both consume the same in-memory book the reader is built from — chapters, the
generated translation, and the glosses — and neither calls the API. They part
ways on what a static page can hold: EPUB reflows and keeps the glosses as
tap-to-reveal notes; PDF fixes the two-page spread and leaves the glosses out,
since footnotes would crowd a printed page.
"""
from .epub import write_epub

__all__ = ["write_epub"]
