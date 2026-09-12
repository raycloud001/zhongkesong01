from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class TextProvider(Protocol):
    async def generate_report(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class ProviderUnavailable(RuntimeError):
    """The configured provider cannot currently serve a request."""


class ProviderResponseError(RuntimeError):
    """The provider returned a successful but unusable response."""


def _common_environment() -> dict[str, str]:
    values = {
        "base_url": os.getenv("MODELSCOPE_BASE_URL", "").strip(),
        "api_key": os.getenv("MODELSCOPE_API_KEY", "").strip(),
    }
    if not all(values.values()):
        raise ProviderUnavailable("provider configuration is incomplete")
    return values


def _embedding_dimension_from_env() -> int | None:
    dimension_text = os.getenv("MODELSCOPE_EMBEDDING_DIMENSION", "").strip()
    try:
        dimension = int(dimension_text) if dimension_text else None
    except ValueError as exc:
        raise ProviderUnavailable("provider configuration is incomplete") from exc
    if dimension is not None and dimension <= 0:
        raise ProviderUnavailable("provider configuration is incomplete")
    return dimension


@dataclass(slots=True)
class _ModelScopeClient:
    base_url: str
    api_key: str
    timeout_seconds: float = 30.0
    transport: httpx.AsyncBaseTransport | None = None

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url.rstrip("/"),
                headers=headers,
                timeout=self.timeout_seconds,
                transport=self.transport,
            ) as client:
                response = await client.post(path, json=payload)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("provider request failed") from exc
        try:
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError
            return body
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderResponseError("invalid provider response") from exc


@dataclass(slots=True)
class ModelScopeTextProvider(_ModelScopeClient):
    text_model: str = ""

    @classmethod
    def from_env(cls) -> "ModelScopeTextProvider":
        text_model = os.getenv("MODELSCOPE_MODEL_NAME", "").strip()
        if not text_model:
            raise ProviderUnavailable("provider configuration is incomplete")
        return cls(**_common_environment(), text_model=text_model)

    async def generate_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.text_model:
            raise ProviderUnavailable("text provider configuration is incomplete")
        response = await self._post(
            "/chat/completions",
            {
                "model": self.text_model,
                "messages": [{
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                }],
                "response_format": {"type": "json_object"},
            },
        )
        try:
            content = response["choices"][0]["message"]["content"]
            result = json.loads(content)
            if not isinstance(result, dict):
                raise TypeError
            return result
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ProviderResponseError("invalid text generation response") from exc


@dataclass(slots=True)
class ModelScopeEmbeddingProvider(_ModelScopeClient):
    embedding_model: str = ""
    embedding_dimension: int | None = None

    @classmethod
    def from_env(cls) -> "ModelScopeEmbeddingProvider":
        embedding_model = os.getenv("MODELSCOPE_EMBEDDING_MODEL", "").strip()
        if not embedding_model:
            raise ProviderUnavailable("provider configuration is incomplete")
        return cls(
            **_common_environment(),
            embedding_model=embedding_model,
            embedding_dimension=_embedding_dimension_from_env(),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.embedding_model:
            raise ProviderUnavailable("embedding provider configuration is incomplete")
        response = await self._post("/embeddings", {"model": self.embedding_model, "input": texts})
        try:
            data = response["data"]
            if not isinstance(data, list) or len(data) != len(texts):
                raise TypeError
            ordered = sorted(data, key=lambda item: item["index"])
            if [item["index"] for item in ordered] != list(range(len(texts))):
                raise TypeError
            vectors = [item["embedding"] for item in ordered]
            expected_dimension = self.embedding_dimension
            if expected_dimension is None and vectors:
                expected_dimension = len(vectors[0])
            if expected_dimension is None or expected_dimension <= 0:
                raise TypeError
            for vector in vectors:
                if (
                    not isinstance(vector, list)
                    or len(vector) != expected_dimension
                    or not all(
                        not isinstance(value, bool)
                        and isinstance(value, (int, float))
                        and math.isfinite(value)
                        for value in vector
                    )
                ):
                    raise TypeError
            return [[float(value) for value in vector] for vector in vectors]
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderResponseError("invalid embedding response") from exc


@dataclass(slots=True)
class ModelScopeProvider(_ModelScopeClient):
    """Compatibility adapter for deployments using both remote capabilities."""

    text_model: str | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None

    @classmethod
    def from_env(cls) -> "ModelScopeProvider":
        text_model = os.getenv("MODELSCOPE_MODEL_NAME", "").strip() or None
        embedding_model = os.getenv("MODELSCOPE_EMBEDDING_MODEL", "").strip() or None
        if text_model is None and embedding_model is None:
            raise ProviderUnavailable("provider configuration is incomplete")
        return cls(
            **_common_environment(),
            text_model=text_model,
            embedding_model=embedding_model,
            embedding_dimension=_embedding_dimension_from_env(),
        )

    async def generate_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await ModelScopeTextProvider.generate_report(self, payload)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await ModelScopeEmbeddingProvider.embed(self, texts)
