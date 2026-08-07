import json
import logging
from typing import Any, Callable, Mapping

import requests

from backend.config.settings import Settings, load_settings


logger = logging.getLogger(__name__)


class QueryLlmError(RuntimeError):
    """Base error for QueryLlm failures."""


class QueryLlmTimeoutError(QueryLlmError):
    """Raised when the upstream LLM does not respond within the configured timeout."""


class QueryLlmConnectionError(QueryLlmError):
    """Raised when the client cannot reach the upstream LLM."""


class QueryLlmHttpError(QueryLlmError):
    """Raised when the upstream LLM responds with a non-success HTTP status."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class QueryLlmResponseError(QueryLlmError):
    """Raised when the upstream LLM returns an empty or invalid JSON response."""


class QueryLlm:
    def __init__(
        self,
        settings: Settings | None = None,
        transport: Callable[..., Any] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._settings = settings or load_settings()
        self._transport = transport
        self._clock = clock or __import__("time").monotonic

    def _build_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "model": self._settings.llm_model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self._settings.llm_keep_alive,
            "think": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_predict": self._settings.llm_num_predict,
                "num_ctx": self._settings.llm_num_ctx,
            },
        }

    def _truncate(self, value: str | None) -> str:
        if value is None:
            return ""
        limit = self._settings.llm_log_max_chars
        if limit <= 0 or len(value) <= limit:
            return value
        return value[:limit] + "…"

    def _post(self, payload: Mapping[str, Any]) -> Any:
        try:
            if self._transport is not None:
                return self._transport(self._settings.llm_url, json=payload, timeout=self._settings.llm_timeout)
            return requests.post(
                self._settings.llm_url,
                json=payload,
                timeout=self._settings.llm_timeout,
                **(
                    {
                        "proxies": {
                            "http": self._settings.ollama_http_proxy,
                            "https": self._settings.ollama_http_proxy,
                        }
                    }
                    if self._settings.ollama_http_proxy is not None
                    else {}
                ),
            )
        except requests.exceptions.Timeout as exc:
            raise QueryLlmTimeoutError(f"LLM request timed out after {self._settings.llm_timeout}s") from exc
        except requests.exceptions.ConnectionError as exc:
            raise QueryLlmConnectionError(f"LLM connection error: {exc}") from exc

    def _parse(self, body: str) -> dict[str, Any]:
        body = body.strip()
        if not body:
            raise QueryLlmResponseError("La respuesta del modelo vino vacía.")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            start = body.find("{")
            end = body.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise QueryLlmResponseError(
                    "No se encontró un objeto JSON en la respuesta del modelo."
                )
            return json.loads(body[start : end + 1])

    def request(self, prompt: str) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        payload = self._build_payload(prompt)
        logger.info(
            "llm request start url=%s model=%s timeout=%s",
            self._settings.llm_url,
            self._settings.llm_model,
            self._settings.llm_timeout,
        )
        if self._settings.llm_log_content:
            logger.debug("llm prompt: %s", self._truncate(prompt))
        started = self._clock()
        status_code: int | None = None
        body = ""
        try:
            response = self._post(payload)
            if self._transport is not None and hasattr(response, "raise_for_status"):
                status_code = getattr(response, "status_code", None)
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError:
                    data = {"response": getattr(response, "text", "")}
                body = (data.get("response") or "") if isinstance(data, dict) else ""
            else:
                status_code = getattr(response, "status_code", None)
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError:
                    data = {"response": getattr(response, "text", "")}
                body = (data.get("response") or "") if isinstance(data, dict) else ""
            result = self._parse(body)
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            raise QueryLlmHttpError(status_code or 0, str(exc)) from exc
        except QueryLlmError:
            elapsed = self._clock() - started
            logger.error("llm request failure duration=%s", elapsed)
            raise
        except Exception as exc:
            elapsed = self._clock() - started
            logger.error("llm request failure duration=%s", elapsed)
            raise QueryLlmError(str(exc)) from exc
        elapsed = self._clock() - started
        logger.info(
            "llm request success duration=%s status=%s",
            elapsed,
            status_code,
        )
        if self._settings.llm_log_content:
            logger.debug("llm response: %s", self._truncate(body))
        return result


__all__ = [
    "QueryLlm",
    "QueryLlmError",
    "QueryLlmTimeoutError",
    "QueryLlmConnectionError",
    "QueryLlmHttpError",
    "QueryLlmResponseError",
]
