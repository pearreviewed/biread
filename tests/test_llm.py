"""The provider clients: usage accounting and truncation detection.

Every other test drives a fake model, so these are the only ones exercising the
code that reads a real SDK response.
"""
import pytest
import requests

from biread.llm import anthropic_client, ollama_client, openai_client, get_client


class Box:
    def __init__(self, **fields):
        self.__dict__.update(fields)


# ---------- Anthropic ----------

def anthropic_response(blocks, stop_reason="end_turn", inp=120, out=60):
    return Box(
        content=[Box(type=t, text=x) for t, x in blocks],
        stop_reason=stop_reason,
        usage=Box(input_tokens=inp, output_tokens=out),
    )


@pytest.fixture
def anthropic(monkeypatch):
    calls = {}

    class FakeMessages:
        def create(self, **kwargs):
            calls.update(kwargs)
            return calls["_response"]

    fake = Box(messages=FakeMessages())
    monkeypatch.setattr(anthropic_client.anthropic, "Anthropic", lambda **kw: fake)

    def build(response):
        calls["_response"] = response
        return anthropic_client.AnthropicClient("claude-test", "key"), calls

    return build


def test_anthropic_joins_text_blocks(anthropic):
    client, _ = anthropic(anthropic_response([("text", "Hello "), ("text", "world")]))
    assert client.complete("sys", "user", 8192).text == "Hello world"


def test_anthropic_ignores_non_text_blocks(anthropic):
    client, _ = anthropic(anthropic_response([("thinking", "hmm"), ("text", "Answer")]))
    assert client.complete("sys", "user", 8192).text == "Answer"


def test_anthropic_accumulates_usage(anthropic):
    client, _ = anthropic(anthropic_response([("text", "x")], inp=100, out=50))
    client.complete("sys", "user", 8192)
    client.complete("sys", "user", 8192)
    assert (client.input_tokens, client.output_tokens) == (200, 100)


def test_anthropic_flags_truncation(anthropic):
    client, _ = anthropic(anthropic_response([("text", "cut")], stop_reason="max_tokens"))
    assert client.complete("sys", "user", 8192).truncated is True


def test_anthropic_sends_the_configured_model_and_limit(anthropic):
    client, calls = anthropic(anthropic_response([("text", "x")]))
    client.complete("a system prompt", "a user prompt", 4096)
    assert calls["model"] == "claude-test"
    assert calls["max_tokens"] == 4096
    assert calls["system"] == "a system prompt"
    assert calls["messages"] == [{"role": "user", "content": "a user prompt"}]


# ---------- OpenAI / OpenRouter ----------

def openai_response(content="Hi", finish_reason="stop", usage=Box(prompt_tokens=10, completion_tokens=5)):
    return Box(choices=[Box(message=Box(content=content), finish_reason=finish_reason)], usage=usage)


@pytest.fixture
def openai(monkeypatch):
    calls = {}

    class FakeCompletions:
        def create(self, **kwargs):
            calls.update(kwargs)
            return calls["_response"]

    fake = Box(chat=Box(completions=FakeCompletions()))
    monkeypatch.setattr(openai_client, "OpenAI", lambda **kw: fake)

    def build(response):
        calls["_response"] = response
        return openai_client.OpenAIClient("gpt-test", "key"), calls

    return build


def test_openai_returns_content(openai):
    client, _ = openai(openai_response("Bonjour"))
    result = client.complete("sys", "user", 4096)
    assert result.text == "Bonjour"
    assert result.truncated is False


def test_openai_flags_truncation(openai):
    client, _ = openai(openai_response(finish_reason="length"))
    assert client.complete("sys", "user", 4096).truncated is True


def test_openai_survives_a_gateway_that_omits_usage(openai):
    # Some OpenAI-compatible gateways return no usage block at all.
    client, _ = openai(openai_response(usage=None))
    client.complete("sys", "user", 4096)
    assert (client.input_tokens, client.output_tokens) == (0, 0)


def test_openai_handles_null_content(openai):
    client, _ = openai(openai_response(content=None))
    assert client.complete("sys", "user", 4096).text == ""


# ---------- Ollama ----------

def ollama_payload(content="Salut", done_reason="stop", prompt=7, eval_count=3):
    return {
        "message": {"content": content},
        "done_reason": done_reason,
        "prompt_eval_count": prompt,
        "eval_count": eval_count,
    }


def test_ollama_reads_content_and_usage(monkeypatch):
    monkeypatch.setattr(
        ollama_client.requests, "post",
        lambda *a, **k: Box(raise_for_status=lambda: None, json=lambda: ollama_payload()),
    )
    client = ollama_client.OllamaClient("llama-test", "http://localhost:11434/")
    result = client.complete("sys", "user", 512)
    assert result.text == "Salut"
    assert (client.input_tokens, client.output_tokens) == (7, 3)


def test_ollama_flags_truncation(monkeypatch):
    monkeypatch.setattr(
        ollama_client.requests, "post",
        lambda *a, **k: Box(raise_for_status=lambda: None,
                            json=lambda: ollama_payload(done_reason="length")),
    )
    client = ollama_client.OllamaClient("llama-test", "http://localhost:11434")
    assert client.complete("sys", "user", 512).truncated is True


def test_ollama_retries_then_succeeds(monkeypatch):
    attempts = []

    def flaky(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise requests.ConnectionError("refused")
        return Box(raise_for_status=lambda: None, json=lambda: ollama_payload())

    monkeypatch.setattr(ollama_client.requests, "post", flaky)
    monkeypatch.setattr(ollama_client.time, "sleep", lambda s: None)
    client = ollama_client.OllamaClient("llama-test", "http://localhost:11434")
    assert client.complete("sys", "user", 512).text == "Salut"
    assert len(attempts) == 3


def test_ollama_gives_up_after_the_last_attempt(monkeypatch):
    def always_fails(*args, **kwargs):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(ollama_client.requests, "post", always_fails)
    monkeypatch.setattr(ollama_client.time, "sleep", lambda s: None)
    client = ollama_client.OllamaClient("llama-test", "http://localhost:11434")
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        client.complete("sys", "user", 512)


def test_ollama_strips_a_trailing_slash_from_the_host():
    assert ollama_client.OllamaClient("m", "http://host:11434/")._host == "http://host:11434"


# ---------- dispatch ----------

@pytest.mark.parametrize("provider,expected", [
    ("anthropic", anthropic_client.AnthropicClient),
    ("openai", openai_client.OpenAIClient),
    ("openrouter", openai_client.OpenAIClient),
    ("ollama", ollama_client.OllamaClient),
])
def test_get_client_dispatches_on_provider(provider, expected, config, monkeypatch):
    monkeypatch.setattr(anthropic_client.anthropic, "Anthropic", lambda **kw: Box())
    monkeypatch.setattr(openai_client, "OpenAI", lambda **kw: Box())
    client = get_client(config(provider=provider, model="m"))
    assert isinstance(client, expected)
    assert client.model == "m"
