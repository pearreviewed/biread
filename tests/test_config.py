import pytest

from biread.config import DEFAULT_MAX_COST_USD, DEFAULT_MODEL, load_config, lookup_price
from biread.errors import ConfigError

VARS = [
    "PROVIDER", "MODEL_TRANSLATE", "MAX_COST_USD", "PRICE_PER_MTOK",
    "OLLAMA_HOST", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    # .env is loaded by load_config, so point it somewhere empty too.
    for name in VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("biread.config.load_dotenv", lambda *a, **k: None)


def test_defaults_to_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cfg = load_config()
    assert cfg.provider == "anthropic"
    assert cfg.model == DEFAULT_MODEL["anthropic"]
    assert cfg.max_cost_usd == DEFAULT_MAX_COST_USD
    assert cfg.base_url is None


def test_blank_values_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_TRANSLATE", "   ")
    assert load_config().model == DEFAULT_MODEL["anthropic"]


def test_openrouter_gets_a_base_url(monkeypatch):
    monkeypatch.setenv("PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    assert load_config().base_url == "https://openrouter.ai/api/v1"


def test_ollama_needs_no_key(monkeypatch):
    monkeypatch.setenv("PROVIDER", "ollama")
    cfg = load_config()
    assert cfg.api_key is None
    assert cfg.ollama_host == "http://localhost:11434"


def test_unknown_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("PROVIDER", "hal9000")
    with pytest.raises(ConfigError, match="unknown PROVIDER"):
        load_config()


def test_missing_key_is_rejected(monkeypatch):
    monkeypatch.setenv("PROVIDER", "anthropic")
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY is not set"):
        load_config()


def test_dry_run_does_not_need_a_key():
    # Estimating a cost should not require credentials to be set up first.
    assert load_config(require_key=False).api_key == ""


def test_bad_max_cost_is_rejected(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("MAX_COST_USD", "two dollars")
    with pytest.raises(ConfigError, match="MAX_COST_USD is not a number"):
        load_config()


def test_known_model_is_priced(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_TRANSLATE", "claude-haiku-4-5")
    cfg = load_config()
    assert cfg.cost_capped
    assert cfg.estimate_cost(1_000_000, 1_000_000) == pytest.approx(6.0)


def test_unknown_model_has_no_price(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_TRANSLATE", "some-local-model")
    cfg = load_config()
    assert not cfg.cost_capped
    assert cfg.estimate_cost(1_000_000, 1_000_000) is None


def test_price_override_caps_an_unpriced_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_TRANSLATE", "some-local-model")
    monkeypatch.setenv("PRICE_PER_MTOK", "1.5, 7.5")
    cfg = load_config()
    assert cfg.cost_capped
    assert cfg.estimate_cost(1_000_000, 1_000_000) == pytest.approx(9.0)


def test_malformed_price_override_is_rejected(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("PRICE_PER_MTOK", "3.0")
    with pytest.raises(ConfigError, match="input,output"):
        load_config()


def test_openrouter_model_ids_resolve_to_first_party_pricing():
    assert lookup_price("anthropic/claude-sonnet-4.6") == lookup_price("claude-sonnet-4-6")
    assert lookup_price("anthropic/claude-haiku-4.5") == (1.00, 5.00)


def test_gpt_model_ids_are_priced_too():
    # Without a row here MAX_COST_USD silently cannot be enforced, which is the
    # hole that made the warning and PRICE_PER_MTOK necessary in the first place.
    assert lookup_price("gpt-5.4") == (2.50, 15.00)
    assert lookup_price("openai/gpt-5.6-terra") == (2.50, 15.00)
    assert lookup_price("gpt-5.5") == (5.00, 30.00)


def test_the_gloss_model_follows_the_translation_model(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_TRANSLATE", "claude-opus-4-8")
    cfg = load_config()
    assert cfg.for_glossing().model == "claude-opus-4-8"
    assert cfg.for_glossing().price_per_mtok == (5.00, 25.00)


def test_the_gloss_model_can_be_overridden_downward(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("MODEL_TRANSLATE", "claude-opus-4-8")
    monkeypatch.setenv("MODEL_GLOSS", "claude-haiku-4-5")
    gloss = load_config().for_glossing()
    assert gloss.model == "claude-haiku-4-5"
    assert gloss.price_per_mtok == (1.00, 5.00)
