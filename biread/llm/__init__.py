from ..config import Config
from .base import Completion, LLMClient

__all__ = ["Completion", "LLMClient", "get_client"]


def get_client(cfg: Config) -> LLMClient:
    # Provider SDKs are imported here, not at module load, so the pipeline stays
    # importable where they are absent — a browser (Pyodide) build ships its own
    # client and never reaches this.
    if cfg.provider == "anthropic":
        from .anthropic_client import AnthropicClient
        return AnthropicClient(cfg.model, cfg.api_key)
    if cfg.provider in ("openai", "openrouter"):
        from .openai_client import OpenAIClient
        return OpenAIClient(cfg.model, cfg.api_key, base_url=cfg.base_url)
    if cfg.provider == "ollama":
        from .ollama_client import OllamaClient
        return OllamaClient(cfg.model, cfg.ollama_host)
    raise ValueError(f"unknown provider: {cfg.provider}")
