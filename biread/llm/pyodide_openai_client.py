"""OpenAI-compatible client for an in-browser (Pyodide) build.

The same chat-completions shape serves OpenAI and, at a different base URL,
OpenRouter — which fronts hundreds of models (Qwen, DeepSeek, Gemini, GPT,
Claude…) behind one key. So a reader can bring one OpenRouter key and pick a
model as cheap as Qwen 3 8B or as capable as Sonnet, all through this client.

Like the Anthropic browser client, the request is synchronous so the existing
synchronous pipeline is reused unchanged; that confines it to a web worker, where
a blocking request is allowed. The CLI never imports this.
"""
from __future__ import annotations

import json

from .base import Completion, LLMClient


class PyodideOpenAIClient(LLMClient):
    def __init__(self, model: str, api_key: str, base_url: str = "https://api.openai.com/v1"):
        super().__init__(model)
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"

    def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        from js import XMLHttpRequest

        xhr = XMLHttpRequest.new()
        xhr.open("POST", self._url, False)  # synchronous: blocks the worker until answered
        xhr.setRequestHeader("content-type", "application/json")
        xhr.setRequestHeader("authorization", f"Bearer {self._api_key}")
        # OpenRouter uses these only to label traffic on its dashboard; harmless elsewhere.
        xhr.setRequestHeader("x-title", "Lecteur bilingue")
        xhr.send(json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }))

        if xhr.status != 200:
            raise RuntimeError(_error_message(xhr))
        data = json.loads(xhr.responseText)
        usage = data.get("usage") or {}
        self.input_tokens += usage.get("prompt_tokens", 0)
        self.output_tokens += usage.get("completion_tokens", 0)
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        return Completion(text, choice.get("finish_reason") == "length")


def _error_message(xhr) -> str:
    """The API's own error text (invalid key, rate limit, no credit…), or a fallback."""
    if xhr.status == 0:
        return "could not reach the model provider — check the connection."
    try:
        return json.loads(xhr.responseText)["error"]["message"]
    except Exception:
        return f"HTTP {xhr.status}"
