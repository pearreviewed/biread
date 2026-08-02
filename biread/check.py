"""Look at a finished book the way a person would, at the places books break.

Every extraction fault that made the shelf curated was found by looking at a
rendered page — not by a test, and not by a number. The bar for putting a book
out is the opening, a middle chapter, and the end; this runs that, so approving
a book is reading three spreads rather than remembering how to look at three
spreads.

It reports rather than judges. A page that is thin, or lopsided, or that logs an
error, is a page worth a human's attention — none of which is the same as a book
being wrong, and the last word stays with whoever runs it.
"""
from __future__ import annotations

import http.server
import socketserver
import threading
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from .errors import BireadError

#: Below this many characters a page has effectively nothing on it — a heading
#: alone, or a column that came out empty.
THIN_CHARS = 200
#: One column this many times the other is not two editions differing; it is a
#: page where one side did not arrive.
LOPSIDED = 3.0


@dataclass
class Spread:
    index: int
    french: int
    english: int
    opening: str

    @property
    def summary(self) -> str:
        return f"French {self.french} chars, English {self.english} — {self.opening}"


@dataclass
class Look:
    total: int
    spreads: list[Spread] = field(default_factory=list)
    faults: list[str] = field(default_factory=list)
    shots_dir: Path | None = None


def _serve(directory: Path):
    """A book with an inlined font and a data-URI paper still has to come over
    http for the page to behave as a reader's would."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):   # every GET is not news
            pass

    handler = partial(Quiet, directory=str(directory))

    class Reusable(socketserver.TCPServer):
        allow_reuse_address = True

    server = Reusable(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def spot_check(book: Path, shots_dir: Path | None = None) -> Look:
    """Open the book at three places and report what is there."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BireadError(
            "looking at the book needs the browser engine. Install it with:\n"
            '  pip install -e ".[browser]" && playwright install chromium'
        ) from exc

    book = Path(book).resolve()
    shots = Path(shots_dir) if shots_dir else book.parent / "checks" / book.stem
    shots.mkdir(parents=True, exist_ok=True)
    server = _serve(book.parent)
    port = server.server_address[1]
    look = Look(total=0, shots_dir=shots)
    try:
        with sync_playwright() as play:
            browser = play.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900},
                                        device_scale_factor=2)
                errors: list[str] = []
                page.on("console",
                        lambda m: errors.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"http://127.0.0.1:{port}/{book.name}")
                page.wait_for_selector("#stage-wrap .page-left", timeout=30000)
                # The counter reads "207+" while the book is still being
                # paginated; the total is not a total until the plus goes.
                page.wait_for_function(
                    "() => { const c = document.getElementById('counter');"
                    "return c && c.textContent && !c.textContent.includes('+'); }",
                    timeout=60000)

                look.total = int(page.inner_text("#counter").split("/")[1])
                places = [("opening", 1), ("middle", max(1, look.total // 2)),
                          ("end", look.total)]
                for name, target in places:
                    look.spreads.append(_at(page, name, target, shots, look))
                if errors:
                    look.faults.append(f"the page logged {len(errors)}: {errors[0][:120]}")
            finally:
                browser.close()
    finally:
        server.shutdown()
    return look


def _at(page, name: str, target: int, shots: Path, look: Look) -> Spread:
    page.click("#counter")
    page.wait_for_selector("#counter-input:not([hidden])")
    page.fill("#counter-input", str(target))
    page.press("#counter-input", "Enter")
    page.wait_for_timeout(1000)

    french = " ".join(page.inner_text("#stage-wrap .page-left").split())
    english = " ".join(page.inner_text("#stage-wrap .page-right").split())
    page.screenshot(path=str(shots / f"{name}.png"))

    if min(len(french), len(english)) < THIN_CHARS:
        look.faults.append(
            f"the {name} spread is nearly empty on one side "
            f"(French {len(french)}, English {len(english)})")
    elif max(len(french), len(english)) > min(len(french), len(english)) * LOPSIDED:
        look.faults.append(
            f"the {name} spread is lopsided (French {len(french)}, English {len(english)}) "
            f"— one side may not have arrived")
    return Spread(index=target, french=len(french), english=len(english),
                  opening=french[:60] or "(nothing)")
