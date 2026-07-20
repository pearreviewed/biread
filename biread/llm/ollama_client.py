import time

import requests

from .base import Completion, LLMClient

ATTEMPTS = 3
TIMEOUT_SECONDS = 120


class OllamaClient(LLMClient):
    def __init__(self, model: str, host: str):
        super().__init__(model)
        self._host = host.rstrip("/")

    def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        # No SDK here, so retry with exponential backoff by hand.
        last_error: Exception | None = None
        for attempt in range(ATTEMPTS):
            try:
                response = requests.post(
                    f"{self._host}/api/chat", json=body, timeout=TIMEOUT_SECONDS
                )
                response.raise_for_status()
                data = response.json()
            except requests.RequestException as e:
                last_error = e
                if attempt < ATTEMPTS - 1:
                    time.sleep(2**attempt)
                continue
            self.input_tokens += data.get("prompt_eval_count", 0)
            self.output_tokens += data.get("eval_count", 0)
            return Completion(
                data["message"]["content"], data.get("done_reason") == "length"
            )
        raise RuntimeError(
            f"Ollama request failed after {ATTEMPTS} attempts: {last_error}"
        ) from last_error
