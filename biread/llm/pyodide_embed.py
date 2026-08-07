"""Embeddings for an in-browser build, via any OpenAI-compatible endpoint.

The same `/embeddings` shape serves OpenRouter (a cloud multilingual model) and a
local Ollama (`http://localhost:11434/v1`, running BGE-M3 for free). Its vectors
feed `align.align_published(embed=…)`, which matches the two editions by meaning.

Synchronous, like the chat clients, so it runs in the worker where blocking is
allowed. Texts are sent in batches to keep each request small; the caller gets one
vector per text, in order.
"""
from __future__ import annotations

import json

#: Enough texts per request to be efficient without an unwieldy body; a chapter's
#: worth of paragraphs at a time.
BATCH = 64


class PyodideEmbedder:
    def __init__(self, model: str, api_key: str, base_url: str):
        self.model = model
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/embeddings"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            vectors.extend(self._embed_batch(texts[start:start + BATCH]))
        return vectors

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        from js import XMLHttpRequest

        xhr = XMLHttpRequest.new()
        xhr.open("POST", self._url, False)  # synchronous: blocks the worker until answered
        xhr.setRequestHeader("content-type", "application/json")
        if self._api_key:
            xhr.setRequestHeader("authorization", f"Bearer {self._api_key}")
        # An empty string embeds to nothing useful and some servers reject it.
        payload = [t if t.strip() else " " for t in batch]
        xhr.send(json.dumps({"model": self.model, "input": payload}))

        if xhr.status != 200:
            raise RuntimeError(_error_message(xhr))
        data = json.loads(xhr.responseText).get("data") or []
        # Order is not guaranteed by the spec, so place each vector by its index.
        out: list[list[float]] = [[] for _ in batch]
        for i, item in enumerate(data):
            out[item.get("index", i)] = item.get("embedding") or []
        return out


def _error_message(xhr) -> str:
    if xhr.status == 0:
        return ("could not reach the embedding model. If it is local, start Ollama "
                "and allow this page (OLLAMA_ORIGINS); otherwise check the connection.")
    try:
        return json.loads(xhr.responseText)["error"]["message"]
    except Exception:
        return f"HTTP {xhr.status}"
