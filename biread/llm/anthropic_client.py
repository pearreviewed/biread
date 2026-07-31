import anthropic

from .base import REQUEST_TIMEOUT_SECONDS, Completion, LLMClient


class AnthropicClient(LLMClient):
    def __init__(self, model: str, api_key: str):
        super().__init__(model)
        # max_retries=2 -> 3 attempts total, with the SDK's exponential backoff —
        # which a call that never returns never reaches, hence the timeout.
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=2,
                                           timeout=REQUEST_TIMEOUT_SECONDS)

    def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        text = "".join(b.text for b in response.content if b.type == "text")
        return Completion(text, response.stop_reason == "max_tokens")
