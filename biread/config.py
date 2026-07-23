"""Provider, model, and spend-cap settings, read from the environment (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace

try:
    from dotenv import load_dotenv
except ImportError:  # absent in a browser build, where there is no .env to read
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False

from .errors import ConfigError

API_KEY_VAR = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": None,
}

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_MAX_COST_USD = 2.00

DEFAULT_MODEL = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-5.4",
    "openrouter": "anthropic/claude-sonnet-4.6",
    "ollama": "llama3.1",
}

# USD per million (input, output) tokens. Feeds the spend estimate and the
# MAX_COST_USD cap only — never the request itself. A model missing from this
# table still works; set PRICE_PER_MTOK to give it a cap.
# Checked against each provider's pricing page in July 2026. Rates drift, and a
# stale row silently mis-reports spend — PRICE_PER_MTOK overrides any of this.
PRICING_PER_MTOK = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "gpt-5-5": (5.00, 30.00),
    "gpt-5-6-sol": (5.00, 30.00),
    "gpt-5-4": (2.50, 15.00),
    "gpt-5-6-terra": (2.50, 15.00),
    "gpt-5-6-luna": (1.00, 6.00),
    "gpt-5-4-mini": (0.75, 4.50),
}


def _pricing_key(model: str) -> str:
    """Normalise a model id to its pricing-table key.

    OpenRouter namespaces ids and spells versions with dots
    ("anthropic/claude-sonnet-4.6"); the table is keyed by the first-party form.
    """
    return model.rsplit("/", 1)[-1].replace(".", "-")


def lookup_price(model: str) -> tuple[float, float] | None:
    return PRICING_PER_MTOK.get(_pricing_key(model))


@dataclass(frozen=True)
class Config:
    provider: str
    model: str
    model_gloss: str
    api_key: str | None
    ollama_host: str
    base_url: str | None
    max_cost_usd: float
    price_per_mtok: tuple[float, float] | None

    def for_glossing(self) -> "Config":
        """The same settings pointed at the gloss model, priced accordingly."""
        return replace(
            self,
            model=self.model_gloss,
            price_per_mtok=lookup_price(self.model_gloss) or self.price_per_mtok,
        )

    @property
    def cost_capped(self) -> bool:
        """Whether MAX_COST_USD can actually be enforced for this model."""
        return self.price_per_mtok is not None

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float | None:
        if self.price_per_mtok is None:
            return None
        in_rate, out_rate = self.price_per_mtok
        return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000


def _env(name: str) -> str:
    """Read an env var, treating present-but-blank the same as unset."""
    return os.environ.get(name, "").strip()


def _float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} is not a number: {raw!r}") from None


def _price_override() -> tuple[float, float] | None:
    raw = _env("PRICE_PER_MTOK")
    if not raw:
        return None
    parts = raw.split(",")
    if len(parts) != 2:
        raise ConfigError(
            f"PRICE_PER_MTOK must be 'input,output' USD per million tokens, got {raw!r}"
        )
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        raise ConfigError(f"PRICE_PER_MTOK values are not numbers: {raw!r}") from None


def load_config(require_key: bool = True) -> Config:
    """Read configuration from the environment.

    `require_key=False` is for paths that never call the API (--dry-run), so a
    cost estimate does not depend on having credentials set up yet.
    """
    load_dotenv()

    provider = (_env("PROVIDER") or "anthropic").lower()
    if provider not in API_KEY_VAR:
        raise ConfigError(
            f"unknown PROVIDER {provider!r} — expected one of: {', '.join(API_KEY_VAR)}"
        )

    model = _env("MODEL_TRANSLATE") or DEFAULT_MODEL[provider]
    # Glossing looks mechanical and is not: it needs the auxiliary in
    # "elle s'est assise", the infinitive behind "ils virent", and the
    # surface copied accent for accent or the unit is discarded. It gets the
    # translation model unless you deliberately choose something cheaper.
    model_gloss = _env("MODEL_GLOSS") or model

    api_key = None
    key_var = API_KEY_VAR[provider]
    if key_var:
        api_key = _env(key_var)
        if not api_key and require_key:
            raise ConfigError(
                f"PROVIDER is {provider!r} but {key_var} is not set.\n"
                f"Add it to .env (see .env.example) and try again."
            )

    return Config(
        provider=provider,
        model=model,
        model_gloss=model_gloss,
        api_key=api_key,
        ollama_host=_env("OLLAMA_HOST") or DEFAULT_OLLAMA_HOST,
        base_url=OPENROUTER_BASE_URL if provider == "openrouter" else None,
        max_cost_usd=_float("MAX_COST_USD", DEFAULT_MAX_COST_USD),
        price_per_mtok=_price_override() or lookup_price(model),
    )
