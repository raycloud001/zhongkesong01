import json

import httpx
import pytest

from app.ai.provider import (
    ModelScopeEmbeddingProvider,
    ModelScopeProvider,
    ModelScopeTextProvider,
    ProviderResponseError,
    ProviderUnavailable,
)


def provider(handler, *, dimension: int | None = None) -> ModelScopeProvider:
    return ModelScopeProvider(
        base_url="https://modelscope.test/v1",
        api_key="test-token",
        text_model="text-model",
        embedding_model="embedding-model",
        embedding_dimension=dimension,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.anyio
async def test_generate_report_parses_json_object_and_sends_configured_model():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "text-model"
        assert body["messages"] == [{"role": "user", "content": '{"answer":"示例"}'}]
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"summary":"可验证"}'}}]})

    result = await provider(handler).generate_report({"answer": "示例"})

    assert result == {"summary": "可验证"}


@pytest.mark.anyio
async def test_embed_returns_vectors_in_input_order():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        return httpx.Response(
            200,
            json={"data": [{"index": 1, "embedding": [3.0, 4.0]}, {"index": 0, "embedding": [1.0, 2.0]}]},
        )

    assert await provider(handler, dimension=2).embed(["甲", "乙"]) == [[1.0, 2.0], [3.0, 4.0]]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        {"choices": []},
        {"choices": [{"message": {"content": "not-json"}}]},
        {"choices": [{"message": {"content": "[]"}}]},
    ],
)
async def test_generate_report_rejects_malformed_responses(response):
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    with pytest.raises(ProviderResponseError, match="invalid text generation response"):
        await provider(handler).generate_report({"private": "must not leak"})


@pytest.mark.anyio
@pytest.mark.parametrize(
    "response",
    [
        {"data": [{"index": 0, "embedding": [1.0, 2.0]}]},
        {"data": [{"index": 0, "embedding": [1.0, "bad"]}, {"index": 1, "embedding": [2.0, 3.0]}]},
        {"data": [{"index": 0, "embedding": [1.0, 2.0]}, {"index": 1, "embedding": [3.0]}]},
    ],
)
async def test_embed_rejects_missing_or_malformed_vectors(response):
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response)

    with pytest.raises(ProviderResponseError, match="invalid embedding response"):
        await provider(handler).embed(["甲", "乙"])


@pytest.mark.anyio
async def test_embed_rejects_configured_dimension_mismatch():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]})

    with pytest.raises(ProviderResponseError, match="invalid embedding response"):
        await provider(handler, dimension=3).embed(["甲"])


@pytest.mark.anyio
async def test_missing_configuration_is_explicitly_unavailable(monkeypatch):
    for name in (
        "MODELSCOPE_BASE_URL",
        "MODELSCOPE_API_KEY",
        "MODELSCOPE_MODEL_NAME",
        "MODELSCOPE_EMBEDDING_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ProviderUnavailable, match="provider configuration is incomplete"):
        ModelScopeProvider.from_env()


def test_text_provider_configuration_does_not_require_embedding_model(monkeypatch):
    monkeypatch.setenv("MODELSCOPE_BASE_URL", "https://modelscope.test/v1")
    monkeypatch.setenv("MODELSCOPE_API_KEY", "text-token")
    monkeypatch.setenv("MODELSCOPE_MODEL_NAME", "text-model")
    monkeypatch.delenv("MODELSCOPE_EMBEDDING_MODEL", raising=False)

    configured = ModelScopeTextProvider.from_env()

    assert configured.text_model == "text-model"


def test_embedding_provider_configuration_does_not_require_text_model(monkeypatch):
    monkeypatch.setenv("MODELSCOPE_BASE_URL", "https://modelscope.test/v1")
    monkeypatch.setenv("MODELSCOPE_API_KEY", "embedding-token")
    monkeypatch.setenv("MODELSCOPE_EMBEDDING_MODEL", "embedding-model")
    monkeypatch.delenv("MODELSCOPE_MODEL_NAME", raising=False)

    configured = ModelScopeEmbeddingProvider.from_env()

    assert configured.embedding_model == "embedding-model"


def test_combined_provider_requires_only_model_used_by_each_method(monkeypatch):
    monkeypatch.setenv("MODELSCOPE_BASE_URL", "https://modelscope.test/v1")
    monkeypatch.setenv("MODELSCOPE_API_KEY", "shared-token")
    monkeypatch.setenv("MODELSCOPE_MODEL_NAME", "text-model")
    monkeypatch.delenv("MODELSCOPE_EMBEDDING_MODEL", raising=False)
    configured = ModelScopeProvider.from_env()

    assert configured.text_model == "text-model"
    assert configured.embedding_model is None


@pytest.mark.anyio
async def test_combined_provider_reports_only_the_missing_capability_when_called(monkeypatch):
    monkeypatch.setenv("MODELSCOPE_BASE_URL", "https://modelscope.test/v1")
    monkeypatch.setenv("MODELSCOPE_API_KEY", "shared-token")
    monkeypatch.setenv("MODELSCOPE_EMBEDDING_MODEL", "embedding-model")
    monkeypatch.delenv("MODELSCOPE_MODEL_NAME", raising=False)
    configured = ModelScopeProvider.from_env()

    with pytest.raises(ProviderUnavailable, match="text provider configuration is incomplete"):
        await configured.generate_report({"answer": "不会发送"})


@pytest.mark.anyio
async def test_upstream_failure_is_sanitized_and_not_retried():
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, text="upstream leaked details")

    with pytest.raises(ProviderUnavailable, match="provider request failed") as error:
        await provider(handler).generate_report({"secret": "user input"})

    assert calls == 1
    assert "upstream leaked details" not in str(error.value)
    assert "user input" not in str(error.value)


@pytest.mark.anyio
async def test_non_json_upstream_success_is_a_sanitized_response_error():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="private malformed content")

    with pytest.raises(ProviderResponseError, match="invalid provider response") as error:
        await provider(handler).embed(["private input"])

    assert "private malformed content" not in str(error.value)


@pytest.mark.anyio
async def test_transport_error_is_sanitized_and_not_retried():
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("secret network detail", request=request)

    with pytest.raises(ProviderUnavailable, match="provider request failed") as error:
        await provider(handler).embed(["private input"])

    assert calls == 1
    assert "secret network detail" not in str(error.value)


@pytest.mark.anyio
@pytest.mark.parametrize("embedding", [[True, False], []])
async def test_embed_rejects_boolean_and_empty_vectors(embedding):
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": embedding}]})

    with pytest.raises(ProviderResponseError, match="invalid embedding response"):
        await provider(handler).embed(["甲"])
