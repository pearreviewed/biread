"""The gloss pass's transport, driven in a real browser.

`web/gloss-pool.js` is the one part of a build that had to move out of the
engine: the engine's client blocks the worker until each answer arrives, so
glossing a long book was hours of waiting end to end with nothing overlapping.
What is worth testing here is exactly what moved — how many requests are in
flight, what happens to a provider saying "not so fast", and that a reply
nothing can be anchored in still reaches the rescue pass.

None of it needs Pyodide: `pyodide` is read from the global scope at call time
and a stub stands in for it, counting what the engine was asked to absorb.

Requires `pip install -e ".[browser]"` plus `playwright install chromium`.
"""
import functools
import http.server
import json
import shutil
import threading
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="playwright not installed")

ROOT = Path(__file__).resolve().parent.parent

#: A page that loads the real transport, with the engine and the network stubbed.
HARNESS = """<!doctype html><meta charset=utf-8>
<script>
// The engine, as far as the pool is concerned: two functions and a tally.
window.seen = { took: [], off: [], live: 0, peak: 0 };
window.pyodide = { globals: { get: (name) => {
  const fn = name === "gloss_take"
    ? (n, text) => { seen.took.push([n, text]); return text.indexOf("@@@") === 0 ? 1 : 0; }
    : (n) => { seen.off.push(n); };
  fn.destroy = () => {};
  return fn;
} } };
// The network. Every call records how many were in the air at its busiest.
window.replies = [];
window.fetch = async (url, opts) => {
  seen.live++; seen.peak = Math.max(seen.peak, seen.live);
  const body = JSON.parse(opts.body);
  const said = replies.length ? replies.shift() : { status: 200 };
  await new Promise((r) => setTimeout(r, said.wait == null ? 20 : said.wait));
  seen.live--;
  return {
    status: said.status,
    headers: { get: () => said.retryAfter || null },
    json: async () => said.status === 200 ? {
      choices: [{ message: { content: said.text == null ? "@@@0@@@\\nun" : said.text },
                  finish_reason: said.truncated ? "length" : "stop" }],
      usage: { prompt_tokens: 10, completion_tokens: 40 },
      url, model: body.model,
    } : { error: { message: "no" } },
  };
};
</script>
<script src="gloss-pool.js"></script>
"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("pool")
    shutil.copy(ROOT / "web" / "gloss-pool.js", root / "gloss-pool.js")
    (root / "index.html").write_text(HARNESS, encoding="utf-8")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *args, **kwargs: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()


@pytest.fixture
def page(browser, site):
    page = browser.new_page()
    page.goto(site)
    yield page
    page.close()


def task(count, **over):
    return {
        "system": "gloss this", "retry": "gloss this, properly", "maxTokens": 8192,
        "batches": [{"n": n, "prompt": f"paragraph {n}"} for n in range(count)],
        **over,
    }


def run(page, count, cfg=None, replies=None):
    page.evaluate("(r) => { window.replies = r; }", replies or [])
    return page.evaluate(
        "([t, c]) => glossInParallel(t, c)",
        [task(count), {"provider": "openrouter", "baseUrl": "https://openrouter.ai/api/v1",
                       "key": "sk-test", "model": "a-model", **(cfg or {})}],
    )


def test_the_requests_overlap(page):
    """The whole point. One at a time is what made a book of 1,500 paragraphs an
    afternoon, and the waiting is nearly all of it."""
    used = run(page, 20)
    seen = page.evaluate("() => seen")
    assert seen["peak"] == 6
    assert len(seen["took"]) == 20
    assert used == {"in": 200, "out": 800, "retryIn": 0, "retryOut": 0, "resent": 0}


def test_a_short_book_asks_for_no_more_hands_than_it_has_batches(page):
    run(page, 2)
    assert page.evaluate("() => seen.peak") == 2


def test_a_model_on_the_readers_own_machine_is_asked_once_at_a_time(page):
    """A second request there does not overlap the first, it queues behind it on
    the same card, and six at once only makes the machine slower at all of them."""
    run(page, 8, cfg={"local": True})
    assert page.evaluate("() => seen.peak") == 1


def test_every_batch_is_written_off_exactly_once(page):
    """Written off is how a batch reaches the rescue pass. A batch that anchored
    still goes through it, because a paragraph inside it may not have."""
    run(page, 5)
    assert sorted(page.evaluate("() => seen.off")) == [0, 1, 2, 3, 4]


def test_a_reply_that_will_not_parse_is_asked_for_once_more(page):
    """The same two attempts the engine has always made, the second carrying the
    stricter note."""
    used = run(page, 1, replies=[{"status": 200, "text": "I cannot do that."}])
    took = page.evaluate("() => seen.took")
    assert len(took) == 2
    assert page.evaluate("() => seen.off") == [0]
    # And the second send is counted as what it is. An estimate prices one send a
    # batch, so this is spend nothing has ever quoted for, and the engine cannot
    # see it: these calls are the page's, not the engine's.
    assert (used["resent"], used["retryIn"], used["retryOut"]) == (1, 10, 40)


def test_a_provider_saying_not_so_fast_is_waited_out(page):
    """A 429 is the ordinary cost of six at once, and losing the batch over it
    would make the concurrency worse than the queue it replaced."""
    run(page, 1, replies=[{"status": 429, "retryAfter": "0", "wait": 0}])
    took = page.evaluate("() => seen.took")
    assert len(took) == 1, "the batch was retried, not abandoned"


def test_a_call_that_is_refused_leaves_the_batch_to_the_rescue(page):
    """A key the provider will not take is not a thing to retry. The batch is
    written off, and the rescue pass tries its paragraphs one at a time on the
    engine's own client, where the error can be reported properly."""
    run(page, 1, replies=[{"status": 401, "wait": 0}])
    assert page.evaluate("() => seen.took") == []
    assert page.evaluate("() => seen.off") == [0]


def test_the_anthropic_shape_is_sent_to_the_anthropic_endpoint(page):
    """One key, two provider shapes: a system prompt beside the messages rather
    than inside them, and the header that lets a browser talk to it at all."""
    page.evaluate("""() => {
      window.sent = [];
      const real = window.fetch;
      window.fetch = (url, opts) => { sent.push([url, opts]); return real(url, opts); };
    }""")
    page.evaluate(
        "([t, c]) => glossInParallel(t, c)",
        [task(1), {"provider": "anthropic", "baseUrl": "", "key": "sk-ant", "model": "claude"}],
    )
    url = page.evaluate("() => sent[0][0]")
    headers = page.evaluate("() => sent[0][1].headers")
    body = json.loads(page.evaluate("() => sent[0][1].body"))
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "sk-ant"
    assert headers["anthropic-dangerous-direct-browser-access"] == "true"
    assert body["system"] == "gloss this"
    assert body["messages"] == [{"role": "user", "content": "paragraph 0"}]
