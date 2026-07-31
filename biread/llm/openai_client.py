from openai import OpenAI

from .base import REQUEST_TIMEOUT_SECONDS, Completion, LLMClient


class OpenAIClient(LLMClient):
    """Also serves OpenRouter, which speaks the same chat-completions API —
    same client, different base_url."""

    def __init__(self, model: str, api_key: str, base_url: str | None = None):
        super().__init__(model)
        # A retry only helps a call that fails. Without a timeout short enough to
        # fail, max_retries never gets its turn — see base.REQUEST_TIMEOUT_SECONDS.
        self._client = OpenAI(api_key=api_key, base_url=base_url, max_retries=2,
                              timeout=REQUEST_TIMEOUT_SECONDS)

    def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        # OpenAI-compatible gateways don't all return usage.
        if response.usage:
            self.input_tokens += response.usage.prompt_tokens
            self.output_tokens += response.usage.completion_tokens
        choice = response.choices[0]
        return Completion(choice.message.content or "", choice.finish_reason == "length")
