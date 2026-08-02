"""Embedding from this machine, without reaching one.

The vectors matter less here than the handling around them: a batch that comes
back out of order, an endpoint that is not running, an empty paragraph. Each has
a wrong answer that looks like a right one — a mis-ordered vector aligns the
wrong paragraphs and nothing about the book looks broken afterwards.
"""
from __future__ import annotations

import pytest

from biread.llm.embed import BATCH, Embedder


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


@pytest.fixture
def posted(monkeypatch):
    """Every request the embedder makes, and a canned reply for each."""
    calls = []

    def reply(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}, "input": json["input"],
                      "model": json["model"]})
        return FakeResponse({
            "data": [{"index": i, "embedding": [float(i)]} for i in range(len(json["input"]))],
            "usage": {"prompt_tokens": 7},
        })

    monkeypatch.setattr("requests.post", reply)
    return calls


def test_one_vector_per_text_in_the_order_they_were_given(posted):
    out = Embedder("bge-m3").embed(["une", "deux", "trois"])
    assert out == [[0.0], [1.0], [2.0]]


def test_vectors_are_placed_by_index_not_by_arrival(monkeypatch):
    """The spec does not promise order, and a silently transposed pair would
    align two wrong paragraphs while the book still looked fine."""
    def shuffled(url, headers=None, json=None, timeout=None):
        return FakeResponse({"data": [
            {"index": 2, "embedding": [2.0]},
            {"index": 0, "embedding": [0.0]},
            {"index": 1, "embedding": [1.0]},
        ]})

    monkeypatch.setattr("requests.post", shuffled)
    assert Embedder("bge-m3").embed(["a", "b", "c"]) == [[0.0], [1.0], [2.0]]


def test_a_long_book_goes_out_in_batches(posted):
    Embedder("bge-m3").embed([f"paragraphe {n}" for n in range(BATCH + 5)])
    assert len(posted) == 2
    assert len(posted[0]["input"]) == BATCH and len(posted[1]["input"]) == 5


def test_an_empty_paragraph_is_sent_as_something(posted):
    """Some servers reject an empty string outright, and a blank paragraph is a
    normal thing for an edition to contain."""
    Embedder("bge-m3").embed(["", "   ", "vrai"])
    assert posted[0]["input"] == [" ", " ", "vrai"]


def test_a_key_rides_only_where_there_is_one(posted):
    Embedder("m", base_url="http://localhost:11434/v1").embed(["x"])
    assert "authorization" not in posted[0]["headers"], "a local model needs no key"
    Embedder("m", api_key="sk-test", base_url="https://openrouter.ai/api/v1").embed(["x"])
    assert posted[1]["headers"]["authorization"] == "Bearer sk-test"
    assert posted[1]["url"] == "https://openrouter.ai/api/v1/embeddings"


def test_it_counts_what_it_spent(posted):
    embedder = Embedder("bge-m3")
    embedder.embed([f"p{n}" for n in range(BATCH + 1)])
    assert embedder.input_tokens == 14, "both batches counted"


def test_a_model_that_will_not_answer_says_which_one(monkeypatch):
    import requests

    def refuse(*args, **kwargs):
        raise requests.RequestException("connection refused")

    monkeypatch.setattr("requests.post", refuse)
    with pytest.raises(RuntimeError, match="could not reach the embedding model"):
        Embedder("bge-m3").embed(["x"])


def test_a_refusal_is_reported_in_the_provider_words(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: FakeResponse(
        {"error": {"message": "model not found"}}, status=404))
    with pytest.raises(RuntimeError, match="model not found"):
        Embedder("nope", api_key="k").embed(["x"])
