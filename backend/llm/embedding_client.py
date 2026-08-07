"""Embedding client abstraction and Ollama-backed implementation.

Subphase 4.4 introduces a typed embedding boundary that is independent from
persistence, generation configuration, and the rest of the backend. The
client only knows how to ask the configured local Ollama server for one
query vector or a batched, ordered list of document vectors, and how to map
transport-level failures to a small, caller-facing exception hierarchy that
never leaks payloads, vectors, or unrelated configuration.
"""

from __future__ import annotations

import logging
import math
from numbers import Real
from typing import TYPE_CHECKING, Any, Callable, Mapping, Protocol


if TYPE_CHECKING:  # pragma: no cover - typing only
    from backend.config.settings import Settings


logger = logging.getLogger(__name__)


class EmbeddingClientProtocol(Protocol):
    """Provider-neutral embedding client surface.

    ``embed_query`` returns one validated vector for a non-empty query.
    ``embed_documents`` returns one validated vector per input in input order
    for a (possibly empty) list of documents; an empty list yields ``[]``
    without sending any network request.
    """

    def embed_query(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingClientError(RuntimeError):
    """Base error for embedding client failures."""


class EmbeddingConnectionError(EmbeddingClientError):
    """Raised when the HTTP transport cannot reach the embedding server."""


class EmbeddingTimeoutError(EmbeddingClientError):
    """Raised when the HTTP transport times out before a response arrives."""


class EmbeddingResponseError(EmbeddingClientError):
    """Raised for non-success HTTP status, malformed payloads, or invalid vectors.

    Messages include only actionable metadata such as the HTTP status, the
    submitted batch size, or the expected vector count, never input texts or
    complete vectors.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class EmbeddingDimensionError(EmbeddingClientError):
    """Raised when a returned vector length does not match the configured
    expected dimension.

    Messages report expected and actual dimensions only; the offending
    vector values are never included.
    """

    def __init__(
        self,
        message: str,
        expected_dimension: int,
        actual_dimension: int,
    ) -> None:
        super().__init__(message)
        self.expected_dimension = expected_dimension
        self.actual_dimension = actual_dimension


# --- Internal validation helpers -------------------------------------------


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, Real):
        return False
    number = float(value)
    return math.isfinite(number)


def _normalize_vector(
    raw: Any,
    *,
    expected_dimension: int,
    submitted_count: int,
    batch_index: int,
) -> list[float]:
    """Validate and normalize a single vector returned by Ollama.

    Returns a list of floats whose length equals ``expected_dimension`` and
    whose values are finite numerics. Raises the appropriate domain error
    otherwise. ``submitted_count`` and ``batch_index`` are used purely to
    shape safe, actionable error messages.
    """
    if not isinstance(raw, list):
        raise EmbeddingResponseError(
            "embedding entry must be a list ("
            f"batch={batch_index}, submitted={submitted_count})"
        )
    if len(raw) != expected_dimension:
        raise EmbeddingDimensionError(
            "embedding dimension mismatch "
            f"(batch={batch_index}, expected={expected_dimension}, "
            f"actual={len(raw)})",
            expected_dimension=expected_dimension,
            actual_dimension=len(raw),
        )
    normalized: list[float] = []
    for position, value in enumerate(raw):
        if not _is_finite_number(value):
            raise EmbeddingResponseError(
                "embedding contains invalid value at position "
                f"{position} (batch={batch_index})"
            )
        normalized.append(float(value))
    return normalized


def _build_payload(
    *,
    model: str,
    inputs: list[str],
) -> dict[str, Any]:
    return {"model": model, "input": inputs}


def _call_transport(
    transport: Callable[..., Any] | None,
    *,
    url: str,
    payload: Mapping[str, Any],
    timeout: int,
    proxy: str | None,
) -> Any:
    import requests

    try:
        if transport is not None:
            return transport(url, json=dict(payload), timeout=timeout)
        return requests.post(
            url,
            json=dict(payload),
            timeout=timeout,
            **(
                {"proxies": {"http": proxy, "https": proxy}}
                if proxy is not None
                else {}
            ),
        )
    except requests.exceptions.Timeout as exc:
        raise EmbeddingTimeoutError(
            f"embedding request timed out after {timeout}s"
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise EmbeddingConnectionError(
            "embedding connection error"
        ) from exc


# --- Concrete implementation ----------------------------------------------


class OllamaEmbeddingClient:
    """Ollama-backed implementation of :class:`EmbeddingClientProtocol`.

    Configuration is taken from the frozen ``Settings`` and never mutated by
    the client. The HTTP transport is injectable so unit tests can run
    without a running Ollama server. Lifecycle logs intentionally omit
    input texts and complete vectors.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        transport: Callable[..., Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        from backend.config.settings import load_settings

        self._settings = settings if settings is not None else load_settings()
        self._transport = transport
        self._clock = clock or __import__("time").monotonic

    def _validate_non_empty_text(
        self,
        text: Any,
        *,
        label: str,
        index: int | None,
    ) -> str:
        if not isinstance(text, str):
            where = f" (index={index})" if index is not None else ""
            raise ValueError(f"{label}{where} must be a string")
        cleaned = text.strip()
        if not cleaned:
            where = f" at index {index}" if index is not None else ""
            raise ValueError(f"{label}{where} must be a non-empty string")
        return cleaned

    def _validate_documents(self, texts: list[Any]) -> list[str]:
        cleaned: list[str] = []
        for index, item in enumerate(texts):
            cleaned.append(
                self._validate_non_empty_text(item, label="document", index=index)
            )
        return cleaned

    def _post(self, payload: Mapping[str, Any]) -> Any:
        return _call_transport(
            self._transport,
            url=self._settings.embedding_url,
            payload=payload,
            timeout=self._settings.embedding_timeout_seconds,
            proxy=self._settings.ollama_proxy_url,
        )

    def _raise_for_status(self, response: Any, *, batch_index: int) -> None:
        import requests

        status_code = getattr(response, "status_code", None)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            raise EmbeddingResponseError(
                "embedding endpoint returned non-success status "
                f"(batch={batch_index}, status={status_code})",
                status_code=status_code,
            ) from exc

    def _parse_embeddings(
        self,
        data: Any,
        *,
        submitted_count: int,
        batch_index: int,
        status_code: int | None,
    ) -> list[list[float]]:
        if not isinstance(data, dict):
            raise EmbeddingResponseError(
                "embedding response must be a JSON object "
                f"(batch={batch_index}, status={status_code})",
                status_code=status_code,
            )
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list):
            raise EmbeddingResponseError(
                "embedding response missing 'embeddings' list "
                f"(batch={batch_index}, status={status_code})",
                status_code=status_code,
            )
        if len(embeddings) != submitted_count:
            raise EmbeddingResponseError(
                "embedding count mismatch "
                f"(batch={batch_index}, expected={submitted_count}, "
                f"actual={len(embeddings)})",
                status_code=status_code,
            )
        expected_dimension = self._settings.embedding_dimension
        normalized_batch: list[list[float]] = []
        for raw_vector in embeddings:
            normalized_batch.append(
                _normalize_vector(
                    raw_vector,
                    expected_dimension=expected_dimension,
                    submitted_count=submitted_count,
                    batch_index=batch_index,
                )
            )
        return normalized_batch

    def _send_batch(
        self,
        batch: list[str],
        *,
        batch_index: int,
    ) -> list[list[float]]:
        submitted_count = len(batch)
        logger.info(
            "embedding request start batch=%s submitted=%s model=%s timeout=%s",
            batch_index,
            submitted_count,
            self._settings.embedding_model,
            self._settings.embedding_timeout_seconds,
        )
        started = self._clock()
        status_code: int | None = None
        try:
            response = self._post(
                _build_payload(
                    model=self._settings.embedding_model,
                    inputs=batch,
                )
            )
            status_code = getattr(response, "status_code", None)
            self._raise_for_status(response, batch_index=batch_index)
            try:
                data = response.json()
            except ValueError as exc:
                raise EmbeddingResponseError(
                    "embedding response is not valid JSON "
                    f"(batch={batch_index}, status={status_code})",
                    status_code=status_code,
                ) from exc
            vectors = self._parse_embeddings(
                data,
                submitted_count=submitted_count,
                batch_index=batch_index,
                status_code=status_code,
            )
        except EmbeddingClientError:
            elapsed = self._clock() - started
            logger.error(
                "embedding request failure batch=%s duration=%s status=%s",
                batch_index,
                elapsed,
                status_code,
            )
            raise
        except Exception as exc:  # pragma: no cover - defensive transport guard
            elapsed = self._clock() - started
            logger.error(
                "embedding request failure batch=%s duration=%s status=%s",
                batch_index,
                elapsed,
                status_code,
            )
            raise EmbeddingResponseError(
                f"unexpected embedding transport failure (batch={batch_index})",
                status_code=status_code,
            ) from exc
        elapsed = self._clock() - started
        logger.info(
            "embedding request success batch=%s duration=%s status=%s",
            batch_index,
            elapsed,
            status_code,
        )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        cleaned = self._validate_non_empty_text(text, label="query", index=None)
        logger.info(
            "embedding query start model=%s timeout=%s",
            self._settings.embedding_model,
            self._settings.embedding_timeout_seconds,
        )
        started = self._clock()
        try:
            batch = self._send_batch([cleaned], batch_index=0)
        except EmbeddingClientError:
            elapsed = self._clock() - started
            logger.error("embedding query failure duration=%s", elapsed)
            raise
        if not batch:
            elapsed = self._clock() - started
            logger.error("embedding query failure duration=%s no_result", elapsed)
            raise EmbeddingResponseError("embedding query returned no vector")
        elapsed = self._clock() - started
        logger.info(
            "embedding query success duration=%s dimension=%s",
            elapsed,
            len(batch[0]),
        )
        return batch[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if texts is None:
            raise ValueError("documents must be a list")
        if not isinstance(texts, list):
            raise ValueError("documents must be a list")
        if not texts:
            return []
        cleaned = self._validate_documents(texts)
        batch_size = self._settings.embedding_batch_size
        if batch_size <= 0:
            raise EmbeddingResponseError(
                "configured embedding batch size must be positive"
            )
        total = len(cleaned)
        logger.info(
            "embedding documents start count=%s batch_size=%s model=%s",
            total,
            batch_size,
            self._settings.embedding_model,
        )
        started = self._clock()
        results: list[list[float]] = []
        for batch_index, start in enumerate(range(0, total, batch_size)):
            chunk = cleaned[start : start + batch_size]
            batch_results = self._send_batch(chunk, batch_index=batch_index)
            results.extend(batch_results)
        if len(results) != total:
            elapsed = self._clock() - started
            logger.error(
                "embedding documents failure duration=%s reason=incomplete_result",
                elapsed,
            )
            raise EmbeddingResponseError(
                "embedding documents returned incomplete result set "
                f"(expected={total}, actual={len(results)})"
            )
        elapsed = self._clock() - started
        logger.info(
            "embedding documents success count=%s batches=%s duration=%s",
            total,
            (total + batch_size - 1) // batch_size,
            elapsed,
        )
        return results


__all__ = [
    "EmbeddingClientProtocol",
    "EmbeddingClientError",
    "EmbeddingConnectionError",
    "EmbeddingTimeoutError",
    "EmbeddingResponseError",
    "EmbeddingDimensionError",
    "OllamaEmbeddingClient",
]
