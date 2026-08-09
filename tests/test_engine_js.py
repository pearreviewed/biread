"""The real engine, the real page, a stubbed provider: does a book come out?

Everything else about the builder is tested against a stub worker, which is what
keeps that suite offline and fast. What no stub can check is the seam this one
does: the engine really booting Pyodide and the wheel, really planning a gloss
run, really handing its batches to `gloss-pool.js`, and the finished book really
carrying the hover units that came back. Half of that is Python written inside
JavaScript strings, where a typo costs a reader a paid-for build.

Opt-in, because it boots Pyodide from a CDN and reads a bundle that only exists
after `python web/build.py`:

    python web/build.py
    BIREAD_ENGINE_SMOKE=1 pytest tests/test_engine_js.py

Nothing is paid for: the provider is intercepted and answers in its own format.
"""
import functools
import http.server
import json
import os
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright not installed")

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "web" / "dist"

pytestmark = [
    pytest.mark.skipif(not os.environ.get("BIREAD_ENGINE_SMOKE"),
                       reason="boots Pyodide from a CDN; set BIREAD_ENGINE_SMOKE=1"),
    pytest.mark.skipif(not (DIST / "builder.html").exists(),
                       reason="no bundle: run python web/build.py first"),
]

#: Two dozen paragraphs, each carrying a phrase narrow enough to be one hover.
BOOK = "\n\n".join(
    f"Voici le paragraphe numero {n}, et il continue un peu." for n in range(24)
).encode()


def answer(route):
    """The provider, in both of the shapes the engine asks it for."""
    body = json.loads(route.request.post_data)
    system = body.get("system") or next(
        (m["content"] for m in body.get("messages", []) if m["role"] == "system"), "")
    user = next(m["content"] for m in body["messages"] if m["role"] == "user")
    paragraphs = user.split("=== PARAGRAPH ")[1:]
    glossing = "hover units" in system
    blocks = [
        f"@@@{n}@@@\n" + ("le paragraphe ¦ noun ¦ the paragraph" if glossing
                          else f"Here is paragraph number {n}, and it goes on a little.")
        for n in range(len(paragraphs))
    ]
    route.fulfill(status=200, content_type="application/json", body=json.dumps({
        "choices": [{"message": {"content": "\n".join(blocks)}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 300},
    }))


@pytest.fixture(scope="module")
def bundle():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DIST))
    handler.log_message = lambda *args, **kwargs: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/builder.html"
    server.shutdown()


@pytest.fixture
def engine(browser, bundle):
    """A page with the engine booted and the provider answering for nothing."""
    context = browser.new_context()
    calls = []
    context.route("**/api/v1/chat/completions",
                  lambda route: (calls.append(route.request.post_data), answer(route)))
    context.route("**/api/v1/models",
                  lambda route: route.fulfill(status=200, content_type="application/json",
                                              body='{"data": []}'))
    page = context.new_page()
    page.goto(bundle)
    page.wait_for_function("() => S.ready === true", timeout=240000)
    yield page, calls
    context.close()


def build(page):
    page.set_input_files("#f-orig", files=[
        {"name": "livre.txt", "mimeType": "text/plain", "buffer": BOOK}])
    page.wait_for_function("!document.getElementById('to-settings').disabled", timeout=60000)
    page.click("#to-settings")
    page.fill("#key", "sk-or-v1-test")
    page.check("#gloss")
    page.wait_for_function("!document.getElementById('build').disabled", timeout=60000)
    # Priced against what is already held, which lands a moment after the file.
    page.wait_for_timeout(1500)
    page.click("#build")
    page.wait_for_function("!document.getElementById('s-done').hidden", timeout=300000)


def test_a_book_comes_out_with_the_hover_it_was_asked_for(engine):
    page, calls = engine
    build(page)
    assert len(calls) > 0
    html = page.evaluate("() => S.html")
    assert html.count('"units"') == 24, "every paragraph should carry its hover units"
    assert "Here is paragraph number 0" in html


def test_a_build_interrupted_is_a_build_resumed(engine):
    """The whole of it: a machine switched off, the same book brought back, and
    not one paragraph paid for twice."""
    page, calls = engine
    build(page)
    first = page.evaluate("() => S.html")
    # Written a moment after the last batch, in one transaction.
    page.wait_for_timeout(2500)

    calls.clear()
    page.reload()
    page.wait_for_function("() => S.ready === true", timeout=240000)
    page.set_input_files("#f-orig", files=[
        {"name": "livre.txt", "mimeType": "text/plain", "buffer": BOOK}])
    page.wait_for_function("!document.getElementById('to-settings').disabled", timeout=60000)
    page.click("#to-settings")
    page.fill("#key", "sk-or-v1-test")
    page.check("#gloss")
    page.wait_for_timeout(1500)
    assert "already made from an earlier session" in page.eval_on_selector(
        "#fig-detail", "e => e.textContent")

    page.click("#build")
    page.wait_for_function("!document.getElementById('s-done').hidden", timeout=300000)
    assert calls == [], "a resumed build must ask the provider for nothing"
    assert page.evaluate("() => S.html") == first
