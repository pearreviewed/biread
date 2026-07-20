import re

import pytest

from biread.cleanup import Chapter
from biread.config import Config
from biread.llm.base import Completion, LLMClient


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
