"""Static exports of a book: EPUB for e-readers, PDF for print.

Both consume the same in-memory book the reader is built from — chapters and the
generated translation — and neither calls the API. Both also keep the reader's
open-book spread and leave the glosses out: EPUB as a fixed-layout book (French
left, English right, paginated in headless Chromium), PDF as a two-column print
page. Glossing on every phrase would bury a static page, so it stays in the
reader; both exporters need the `[browser]` extra.
"""
from .epub import write_epub
from .pdf import write_pdf

__all__ = ["write_epub", "write_pdf"]
