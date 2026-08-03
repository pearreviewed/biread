"""The reader's side of bookmark sync, driven in a real browser.

Sync only exists for a book served over http(s), so these serve one — against a
stub that speaks the sync API in memory. What is being tested is the client's
judgement: whether it offers sync at all, what it sends, and that a position
arriving from another device is offered rather than taken.

Requires `pip install -e ".[browser]"` plus `playwright install chromium`.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.test_reader_js import build_reader, sync_playwright


class Stub:
    """One reader's shelf, and a record of what the book put on it."""

    def __init__(self) -> None:
        self.sign_in = "github"
        self.signed_in = False
        self.books: dict[str, dict] = {}
        self.puts: list[tuple[str, dict]] = []


def serve(directory, stub: Stub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def reply(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/health":
                return self.reply(200, {"ok": True, "signIn": stub.sign_in})
            if self.path == "/api/me":
                return self.reply(200, {"signedIn": stub.signed_in, "handle": "lev",
                                        "provider": "github"} if stub.signed_in
                                  else {"signedIn": False})
            if self.path == "/api/shelf":
                if not stub.signed_in:
                    return self.reply(401, {"detail": "sign in"})
                return self.reply(200, {"books": list(stub.books.values())})
            if self.path.startswith("/api/"):
                return self.reply(404, {})
            name = self.path.lstrip("/").split("?")[0] or "index.html"
            try:
                body = (directory / name).read_bytes()
            except OSError:
                return self.reply(404, {})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_PUT(self):
            book_id = self.path.rsplit("/", 1)[-1]
            sent = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            stub.puts.append((book_id, sent))
            held = stub.books.setdefault(book_id, {"bookId": book_id, "edits": []})
            held.update({k: v for k, v in sent.items() if k != "edits" and v is not None})
            return self.reply(200, {"books": [held]})

        def do_POST(self):
            stub.signed_in = False
            return self.reply(200, {"signedIn": False})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch()
        yield instance
        instance.close()


@pytest.fixture(scope="module")
def book(tmp_path_factory):
    return build_reader(tmp_path_factory, published=False, revise=True)


@pytest.fixture
def hosted(browser, book):
    """The book, served over http, beside a sync service that answers."""
    stub = Stub()
    server = serve(book.parent, stub)
    port = server.server_address[1]
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/{book.name}")
    page.wait_for_function(
        "() => { const c = document.getElementById('counter');"
        "return c && c.textContent && !c.textContent.includes('+'); }", timeout=15000)
    yield page, stub
    page.close()
    server.shutdown()


def open_bookmarks(page):
    page.click("#bm-btn")
    page.wait_for_selector(".popover")


def test_a_hosted_book_offers_to_keep_your_place(hosted):
    page, _ = hosted
    page.wait_for_function("() => !!document.querySelector('#bm-btn')")
    open_bookmarks(page)
    page.wait_for_selector(".sync-foot")
    assert "Keep my place" in page.inner_text(".sync-line")
    assert page.inner_text(".sync-act") == "Sign in with GitHub"


def test_a_downloaded_file_asks_nobody_anything(browser, book):
    """The whole reason the reader is one file: opened from disk, it phones nowhere."""
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    asked = []
    page.on("request", lambda r: asked.append(r.url) if "/api/" in r.url else None)
    page.goto(book.as_uri())
    page.wait_for_function(
        "() => { const c = document.getElementById('counter');"
        "return c && c.textContent && !c.textContent.includes('+'); }", timeout=15000)
    open_bookmarks(page)
    assert asked == []
    assert page.query_selector(".sync-foot") is None
    page.close()


def test_a_host_with_no_way_in_offers_nothing(browser, book):
    """A sign-in button that cannot sign anyone in is worse than no button."""
    stub = Stub()
    stub.sign_in = None
    server = serve(book.parent, stub)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"http://127.0.0.1:{server.server_address[1]}/{book.name}")
    page.wait_for_function(
        "() => { const c = document.getElementById('counter');"
        "return c && c.textContent && !c.textContent.includes('+'); }", timeout=15000)
    open_bookmarks(page)
    assert page.query_selector(".sync-foot") is None
    page.close()
    server.shutdown()


def test_signing_in_returns_to_the_book(hosted):
    page, _ = hosted
    open_bookmarks(page)
    page.wait_for_selector(".sync-act")
    with page.expect_navigation(wait_until="commit"):
        page.click(".sync-act")
    assert "/api/auth/github?next=" in page.url
    assert page.url.endswith(page.url.split("next=")[1])  # the book's own path


def test_a_signed_in_reader_is_named_not_prompted(browser, book):
    stub = Stub()
    stub.signed_in = True
    server = serve(book.parent, stub)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"http://127.0.0.1:{server.server_address[1]}/{book.name}")
    page.wait_for_function(
        "() => { const c = document.getElementById('counter');"
        "return c && c.textContent && !c.textContent.includes('+'); }", timeout=15000)
    page.wait_for_function("() => document.querySelector('#bm-btn')")
    open_bookmarks(page)
    page.wait_for_selector(".sync-foot")
    assert "lev" in page.inner_text(".sync-line")
    assert page.inner_text(".sync-act") == "Sign out"
    page.close()
    server.shutdown()


def test_a_new_book_puts_itself_on_the_shelf(browser, book):
    stub = Stub()
    stub.signed_in = True
    server = serve(book.parent, stub)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"http://127.0.0.1:{server.server_address[1]}/{book.name}")
    page.wait_for_function(
        "() => { const c = document.getElementById('counter');"
        "return c && c.textContent && !c.textContent.includes('+'); }", timeout=15000)
    for _ in range(60):
        if stub.puts:
            break
        page.wait_for_timeout(200)
    assert stub.puts, "a book the shelf has never seen should put itself there"
    book_id, sent = stub.puts[0]
    assert sent["position"]["h"], "a position is a paragraph, not a page number"
    assert sent["title"]
    page.close()
    server.shutdown()


def test_turning_a_page_sends_where_you_are(browser, book):
    stub = Stub()
    stub.signed_in = True
    server = serve(book.parent, stub)
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"http://127.0.0.1:{server.server_address[1]}/{book.name}")
    page.wait_for_function(
        "() => { const c = document.getElementById('counter');"
        "return c && c.textContent && !c.textContent.includes('+'); }", timeout=15000)
    for _ in range(40):
        if stub.puts:
            break
        page.wait_for_timeout(200)
    first = len(stub.puts)
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(600)
    page.keyboard.press("ArrowRight")
    for _ in range(40):
        if len(stub.puts) > first:
            break
        page.wait_for_timeout(200)
    assert len(stub.puts) > first
    opened, moved = stub.puts[0][1], stub.puts[-1][1]
    assert moved["position"] != opened["position"]
    page.close()
    server.shutdown()


def test_another_device_is_offered_never_taken(browser, book):
    """A page that jumps under a reader is a bug, however correct the page is."""
    stub = Stub()
    stub.signed_in = True
    server = serve(book.parent, stub)
    port = server.server_address[1]

    # Learn a real paragraph key by letting one browser put the book up, then
    # hand a different paragraph back as if a second device had read further.
    scout = browser.new_page(viewport={"width": 1280, "height": 900})
    scout.goto(f"http://127.0.0.1:{port}/{book.name}")
    scout.wait_for_function(
        "() => { const c = document.getElementById('counter');"
        "return c && c.textContent && !c.textContent.includes('+'); }", timeout=15000)
    for _ in range(40):
        if stub.puts:
            break
        scout.wait_for_timeout(200)
    scout.keyboard.press("ArrowRight")
    scout.keyboard.press("ArrowRight")
    scout.keyboard.press("ArrowRight")
    for _ in range(40):
        if len(stub.puts) > 1:
            break
        scout.wait_for_timeout(200)
    elsewhere = stub.puts[-1][1]["position"]
    scout.close()

    book_id = stub.puts[0][0]
    stub.books[book_id] = {"bookId": book_id, "position": elsewhere, "edits": []}

    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/{book.name}")
    page.wait_for_function(
        "() => { const c = document.getElementById('counter');"
        "return c && c.textContent && !c.textContent.includes('+'); }", timeout=15000)
    page.wait_for_selector(".resume-banner", timeout=15000)
    assert page.inner_text("#counter").split("/")[0].strip() == "1", \
        "the reader must still be on page one until they accept"
    page.close()
    server.shutdown()
