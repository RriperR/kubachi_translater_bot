"""HTTP embedding provider для удаленного embedding-сервиса."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from urllib import error, request
from urllib.parse import urlparse

from .base import EmbeddingVector


@dataclass(frozen=True)
class EmbeddingServiceMetadata:
    """Метаданные удаленного embedding-сервиса."""

    provider_name: str
    model_name: str
    version: str
    dimensions: int


class HttpEmbeddingProvider:
    """Embedding provider, обращающийся к внешнему HTTP-сервису."""

    def __init__(self, service_url: str, timeout_seconds: float) -> None:
        """Сохранить параметры подключения к embedding-сервису.

        Args:
            service_url: Базовый URL embedding-сервиса.
            timeout_seconds: Таймаут HTTP-запроса в секундах.
        """
        self._service_url = self._normalize_service_url(service_url)
        self._timeout_seconds = timeout_seconds
        self._metadata: EmbeddingServiceMetadata | None = None
        self.provider_name = ""
        self.model_name = ""
        self.version = ""
        self._dimensions = 0

    @property
    def dimensions(self) -> int:
        """Вернуть размерность embeddings удаленного сервиса.

        Returns:
            Число координат в embedding-векторе.
        """
        if self._dimensions == 0:
            self._get_metadata()
        return self._dimensions

    def embed(self, text: str) -> EmbeddingVector:
        """Построить embedding одного текста через HTTP.

        Args:
            text: Текст запроса.

        Returns:
            Построенный embedding-вектор.
        """
        payload = self._request_json(
            path="/v1/embed",
            payload={"text": text},
        )
        return self._parse_vector(payload["embedding"])

    def embed_many(self, texts: Sequence[str]) -> list[EmbeddingVector]:
        """Построить embeddings для набора текстов через HTTP.

        Args:
            texts: Последовательность текстов для индексации.

        Returns:
            Векторы в исходном порядке.
        """
        if not texts:
            return []
        payload = self._request_json(
            path="/v1/embed-many",
            payload={"texts": list(texts)},
        )
        raw_vectors = self._require_list(payload, "embeddings")
        return [self._parse_vector(raw_vector) for raw_vector in raw_vectors]

    def _get_metadata(self) -> EmbeddingServiceMetadata:
        if self._metadata is not None:
            return self._metadata

        payload = self._request_json(path="/v1/metadata")
        self._metadata = EmbeddingServiceMetadata(
            provider_name=self._require_str(payload, "provider_name"),
            model_name=self._require_str(payload, "model_name"),
            version=self._require_str(payload, "version"),
            dimensions=self._require_int(payload, "dimensions"),
        )
        self.provider_name = self._metadata.provider_name
        self.model_name = self._metadata.model_name
        self.version = self._metadata.version
        self._dimensions = self._metadata.dimensions
        return self._metadata

    def _request_json(
        self,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> dict[str, object]:
        method = "POST" if payload is not None else "GET"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(  # noqa: S310
            url=f"{self._service_url}{path}",
            method=method,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:  # noqa: S310
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Embedding service returned HTTP {exc.code}: {details}") from exc
        except error.URLError as exc:
            raise RuntimeError(
                f"Не удалось подключиться к embedding service: {exc.reason}"
            ) from exc

        try:
            parsed = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Embedding service вернул невалидный JSON") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError("Embedding service вернул неожиданный формат ответа")
        return parsed

    @staticmethod
    def _normalize_service_url(service_url: str) -> str:
        normalized = service_url.rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "RAG_EMBEDDING_SERVICE_URL должен использовать http/https и содержать host"
            )
        return normalized

    @staticmethod
    def _parse_vector(raw_vector: object) -> EmbeddingVector:
        if not isinstance(raw_vector, list):
            raise RuntimeError("Embedding service вернул embedding в неверном формате")
        return EmbeddingVector(tuple(float(value) for value in raw_vector))

    @staticmethod
    def _require_str(payload: dict[str, object], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str):
            raise RuntimeError(f"Embedding service вернул поле {key!r} в неверном формате")
        return value

    @staticmethod
    def _require_int(payload: dict[str, object], key: str) -> int:
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise RuntimeError(f"Embedding service вернул поле {key!r} в неверном формате")
        return int(value)

    @staticmethod
    def _require_list(payload: dict[str, object], key: str) -> list[object]:
        value = payload.get(key)
        if not isinstance(value, list):
            raise RuntimeError(f"Embedding service вернул поле {key!r} в неверном формате")
        return value
