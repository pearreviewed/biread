from ..config import Config
from .anthropic_client import AnthropicClient
from .base import Completion, LLMClient
from .ollama_client import OllamaClient
from .openai_client import OpenAIClient

__all__ = ["Completion", "LLMClient", "get_client"]


def get_client(cfg: Config) -> LLMClient:
    if cfg.provider == "anthropic":
        return AnthropicClient(cfg.model, cfg.api_key)
    if cfg.provider in ("openai", "openrouter"):
        return OpenAIClient(cfg.model, cfg.api_key, base_url=cfg.base_url)
    if cfg.provider == "ollama":
        return OllamaClient(cfg.model, cfg.ollama_host)
    raise ValueError(f"unknown provider: {cfg.provider}")
