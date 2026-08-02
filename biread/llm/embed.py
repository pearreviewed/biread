"""Embeddings from this machine, via any OpenAI-compatible `/embeddings`.

The counterpart to `pyodide_embed`, which only exists inside the browser — so
until now the shelf could be built from the web builder and nowhere else, and
publishing a book meant opening a page to do it. One shape serves both ends of
the price range: OpenRouter for a cloud multilingual model, a local Ollama
(`http://localhost:11434/v1`, BGE-M3) for nothing at all.

Its vectors feed `align.align_published(embed=…)`, which matches two editions by
meaning rather than by shared words.
"""
from __future__ import annotations

from .base import REQUEST_TIMEOUT_SECONDS

#: Enough texts per request to be efficient without an unwieldy body — about a
#: chapter's worth of paragraphs. Matches the browser client, so a book aligned
#: here and a book aligned there are batched the same way.
BATCH = 64

OLLAMA_BASE = "http://localhost:11434/v1"


class Embedder:
    """One vector per text, in the order the texts were given.

    Usage is counted the way the chat clients count theirs, so a caller can price
    a run without threading totals through every return value. Embedding
    endpoints report prompt tokens only; there is no output side to charge for.
    """

    def __init__(self, model: str, api_key: str = "", base_url: str = OLLAMA_BASE):
        self.model = model
        self.input_tokens = 0
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/embeddings"

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            vectors.extend(self._batch(texts[start:start + BATCH]))
        return vectors

    def _batch(self, batch: list[str]) -> list[list[float]]:
        import requests

        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        # An empty string embeds to nothing useful and some servers reject it.
        payload = [t if t.strip() else " " for t in batch]
        try:
            response = requests.post(
                self._url, headers=headers,
                json={"model": self.model, "input": payload},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"could not reach the embedding model at {self._url} — if it is "
                f"local, start Ollama; otherwise check the connection ({exc})"
            ) from exc
        if response.status_code != 200:
            raise RuntimeError(_message(response))

        body = response.json()
        usage = body.get("usage") or {}
        self.input_tokens += usage.get("prompt_tokens") or 0
        # Order is not guaranteed by the spec, so place each vector by its index.
        out: list[list[float]] = [[] for _ in batch]
        for i, item in enumerate(body.get("data") or []):
            out[item.get("index", i)] = item.get("embedding") or []
        return out


def _message(response) -> str:
    try:
        return response.json()["error"]["message"]
    except Exception:
        return f"HTTP {response.status_code}"
