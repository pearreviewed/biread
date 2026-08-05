import os
import pathlib
import re

import pytest

from biread.cleanup import Chapter
from biread.config import Config
from biread.llm.base import Completion, LLMClient

#: Which engines the reader and builder are driven in. Chromium is the ground
#: truth; WebKit is here because Safari has faults Chromium cannot see — it broke
#: a shelf card across a column boundary and left the piece beneath it with no
#: top border, at a width and pixel density Chromium was clean at all of. An
#: engine that is not installed skips rather than fails, and
#: `BIREAD_ENGINES=chromium` narrows a run that needs to be quick.
#: Only the two suites that test what a reader *sees* take this
#: fixture; the sync, counter and gloss-parity suites keep their own Chromium,
#: because they drive logic through a browser rather than layout.
ENGINES = tuple(e.strip() for e in os.environ.get("BIREAD_ENGINES", "chromium,webkit").split(","))


@pytest.fixture(scope="module", params=ENGINES)
def browser(request):
    api = pytest.importorskip("playwright.sync_api", reason="playwright not installed")
    with api.sync_playwright() as playwright:
        engine = getattr(playwright, request.param)
        if not pathlib.Path(engine.executable_path).exists():
            pytest.skip(f"{request.param} not installed: playwright install {request.param}")
        instance = engine.launch()
        yield instance
        instance.close()


class FakeClient(LLMClient):
    """Echoes back a well-formed response for every paragraph it is given.

    `script` overrides the reply for the first N calls, so tests can make the
    model misbehave (bad format, truncation) and check the recovery path.
    """

    def __init__(self, model="fake-model", script=None):
        super().__init__(model)
        self.prompts = []
        self.script = list(script or [])

    def complete(self, system, user, max_tokens):
        self.prompts.append(user)
        self.input_tokens += 100
        self.output_tokens += 50
        if self.script:
            return self.script.pop(0)
        # Echo the source, so alignment tests have real word overlap to work
        # with rather than placeholder text that resembles nothing.
        blocks = re.findall(
            r"=== PARAGRAPH (\d+) ===\n(.*?)(?=\n\n=== PARAGRAPH |\Z)", user, re.S
        )
        body = "\n".join(f"@@@{n}@@@\nEnglish rendering of {t.strip()}" for n, t in blocks)
        return Completion(body, False)


@pytest.fixture
def config():
    def build(**overrides):
        fields = dict(
            provider="anthropic",
            model="fake-model",
            model_gloss="fake-gloss-model",
            api_key="key",
            ollama_host="http://localhost:11434",
            base_url=None,
            max_cost_usd=2.0,
            price_per_mtok=(3.0, 15.0),
        )
        fields.update(overrides)
        return Config(**fields)

    return build


@pytest.fixture
def client():
    return FakeClient()


@pytest.fixture
def make_client():
    """Factory, for tests that need to script how the model misbehaves."""
    return FakeClient


@pytest.fixture
def book():
    return [
        Chapter(None, None, ["Preamble."]),
        Chapter("I", "Le Départ", ["Premier paragraphe.", "Deuxième paragraphe."]),
        Chapter("II", "L'Arrivée", ["Troisième paragraphe."]),
    ]
