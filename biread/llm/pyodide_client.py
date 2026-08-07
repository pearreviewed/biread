"""Anthropic client for an in-browser (Pyodide) build.

Calls the API with the reader's own key straight from the browser — no SDK and
no server of ours. The request is synchronous so the existing (synchronous)
pipeline is reused unchanged; that means it must run off the main thread, in a
web worker, where a blocking request is allowed. The CLI never imports this.
"""
from __future__ import annotations

import json

from .base import Completion, LLMClient

URL = "https://api.anthropic.com/v1/messages"
VERSION = "2023-06-01"


class PyodideAnthropicClient(LLMClient):
    def __init__(self, model: str, api_key: str):
        super().__init__(model)
        self._api_key = api_key

    def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        from js import XMLHttpRequest

        xhr = XMLHttpRequest.new()
        xhr.open("POST", URL, False)  # synchronous: blocks the worker until answered
        xhr.setRequestHeader("content-type", "application/json")
        xhr.setRequestHeader("x-api-key", self._api_key)
        xhr.setRequestHeader("anthropic-version", VERSION)
        xhr.setRequestHeader("anthropic-dangerous-direct-browser-access", "true")
        xhr.send(json.dumps({
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }))

        if xhr.status != 200:
            raise RuntimeError(_error_message(xhr))
        data = json.loads(xhr.responseText)
        usage = data.get("usage") or {}
        self.input_tokens += usage.get("input_tokens", 0)
        self.output_tokens += usage.get("output_tokens", 0)
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        return Completion(text, data.get("stop_reason") == "max_tokens")


def _error_message(xhr) -> str:
    """The API's own error text (invalid key, rate limit, …), or a fallback."""
    if xhr.status == 0:
        return "could not reach the API. Check the connection."
    try:
        return json.loads(xhr.responseText)["error"]["message"]
    except Exception:
        return f"HTTP {xhr.status}"
