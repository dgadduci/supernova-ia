import json
import logging
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

import requests

from backend.config.settings import Settings, load_settings
from backend.observability import (
    COMPONENT_LLM,
    EVENT_LLM_REQUEST,
    EVENT_LLM_REQUEST_TRANSPORT_PHASE,
    emit_event,
)

logger = logging.getLogger(__name__)


class LLMTimingRecorder:
    """Bounded timing recorder invoked by :class:`QueryLlm`.

    The recorder is the safe seam the provider-path coordinator uses
    to capture the moment the existing ``QueryLlm`` boundary was
    requested and the moment it finished normally, with a timeout or
    with a bounded error. The recorder only stores a UTC timestamp
    plus a closed outcome token; it never receives prompt text,
    response bodies, customer text or exception detail.

    The default ``NoopLLMTimingRecorder`` is a no-op so the existing
    non-provider call sites keep their previous behavior. The
    coordinator installs the safe :class:`WorkItemLLMTimingRecorder`
    around its lease/finalization transaction so the captured timing
    fields survive the existing rollback/retry/terminal paths without
    introducing a side transaction for observability.
    """

    def on_requested(self) -> datetime | None:  # pragma: no cover - trivial
        return None

    def on_finished(
        self,
        *,
        outcome: str,
        finished_at: datetime,
    ) -> None:  # pragma: no cover - trivial
        del outcome, finished_at


class NoopLLMTimingRecorder(LLMTimingRecorder):
    """Default recorder used by every existing non-provider call site."""


class WorkItemLLMTimingRecorder(LLMTimingRecorder):
    """Capture-only recorder used by the provider coordinator.

    The recorder captures the moment the worker reaches the existing
    ``QueryLlm`` boundary and the moment the call finishes into a
    closed in-memory snapshot. The coordinator reads the snapshot and
    writes it back through the existing finalize UPDATE so the
    captured timing lands inside the canonical
    lease/finalization transaction without introducing a side
    transaction. The recorder is intentionally fail-soft: any
    unexpected attribute assignment error is swallowed so the LLM
    path can never crash the worker because of a telemetry detail.
    """

    _ALLOWED_OUTCOMES = frozenset({"completed", "timeout", "error"})

    def __init__(self) -> None:
        self.solicitado_en: datetime | None = None
        self.finalizado_en: datetime | None = None
        self.resultado: str | None = None

    def on_requested(self) -> datetime:
        when = datetime.now(tz=timezone.utc)
        try:
            self.solicitado_en = when
        except Exception:
            logger.exception(
                "llm_timing_record_failed",
                extra={"phase": "requested"},
            )
        return when

    def on_finished(
        self,
        *,
        outcome: str,
        finished_at: datetime,
    ) -> None:
        if outcome not in self._ALLOWED_OUTCOMES:
            outcome = "error"
        try:
            self.finalizado_en = finished_at
            self.resultado = outcome
        except Exception:
            logger.exception(
                "llm_timing_record_failed",
                extra={"phase": "finished"},
            )

    def has_any(self) -> bool:
        return (
            self.solicitado_en is not None
            or self.finalizado_en is not None
            or self.resultado is not None
        )


_TLS = threading.local()


def install_llm_timing_recorder(
    recorder: LLMTimingRecorder | None,
    *,
    correlation_id: str | None = None,
) -> None:
    """Install (or clear) the process-local LLM timing recorder.

    The seam exists so the provider coordinator can capture the
    moment the worker reaches the existing ``QueryLlm`` boundary and
    the moment the call finishes without changing the
    :class:`QueryLlm` constructor signature. Every existing caller
    that does not install a recorder continues to use the safe
    no-op recorder, so the change is fully backward compatible.

    When ``correlation_id`` is supplied the value is attached to
    every ``llm_request`` event emitted from the same thread until
    the recorder is cleared. The value is the opaque synthetic
    inbound identifier (``recepciones_mensajes_proveedor.
    identificador_recepcion``) — the existing safe correlation
    field the operator already trusts — and MUST NOT contain
    prompt text, response bodies, customer text or credentials.
    """
    if recorder is None:
        _TLS.recorder = None
        _TLS.correlation_id = None
        return
    _TLS.recorder = recorder
    if correlation_id is None:
        _TLS.correlation_id = None
    else:
        if not isinstance(correlation_id, str):
            correlation_id = str(correlation_id)
        _TLS.correlation_id = correlation_id[:64]


def _current_llm_timing_recorder() -> LLMTimingRecorder:
    recorder = getattr(_TLS, "recorder", None)
    if recorder is None:
        return NoopLLMTimingRecorder()
    return recorder


def _current_llm_correlation_id() -> str | None:
    return getattr(_TLS, "correlation_id", None)


def current_llm_correlation_id() -> str | None:
    """Return the thread-local provider correlation identifier.

    The helper is shared by the :class:`QueryLlm` and
    :class:`OllamaEmbeddingClient` boundaries so both clients emit
    the exact same opaque synthetic inbound value when the
    provider coordinator installs one for the current turn.

    The value is the bounded opaque correlation the coordinator
    already installs for ``llm_request`` events - never prompt
    text, response bodies, customer text or credentials. The
    helper returns ``None`` outside the provider scope so
    direct non-provider calls retain the previous
    uncorrelated behavior.
    """
    return _current_llm_correlation_id()


def reset_llm_timing_recorder() -> None:
    """Clear the process-local LLM timing recorder (test seam)."""
    _TLS.recorder = None
    _TLS.correlation_id = None


def _emit_llm_transport_phase(
    *,
    phase: str,
    elapsed_ms: int | None,
    http_status: int | None,
    response_bytes: int | None,
    correlation_id: str | None,
) -> None:
    """Emit one bounded ``llm_request_transport_phase`` observation.

    The diagnostic helper is the safe seam the
    :class:`QueryLlm` boundary uses to surface the last client-side
    transport phase reached during a request/response cycle. The
    payload is allowlist-bounded and privacy-safe by construction:
    only the closed phase token, bounded elapsed milliseconds,
    optional bounded HTTP status, optional bounded response byte
    count and the existing opaque correlation identifier are
    permitted. No prompt, response body, URL, proxy value, header,
    credential or exception text is ever included.

    The helper MUST NOT mutate the surrounding business state. The
    existing ``emit_event`` contract already swallows validation
    failures and stream errors without raising; this wrapper keeps
    the diagnostic strictly observational so a misconfigured
    emitter cannot break :class:`QueryLlm.request`.
    """
    try:
        emit_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase=phase,
            elapsed_ms=elapsed_ms,
            http_status=http_status,
            response_bytes=response_bytes,
            correlation_id=correlation_id,
        )
    except Exception:
        logger.exception(
            "llm_transport_phase_emit_failed",
            extra={"phase": phase},
        )


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
                            "http": self._settings.ollama_proxy_url,
                            "https": self._settings.ollama_proxy_url,
                        }
                    }
                    if self._settings.ollama_proxy_url is not None
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

    def request(
        self,
        prompt: str,
        *,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        payload = self._build_payload(prompt)
        logger.info(
            "llm request start model=%s timeout=%s prompt_length=%s",
            self._settings.llm_model,
            self._settings.llm_timeout,
            len(prompt),
        )
        # Resolve the correlation id once. An explicit kwarg wins so
        # the provider path can override the thread-local when it
        # needs to attach a custom opaque identifier; otherwise the
        # thread-local value installed by the coordinator wins so
        # every LLM event emitted from this call carries the same
        # safe correlation metadata.
        effective_correlation_id = (
            correlation_id
            if correlation_id is not None
            else _current_llm_correlation_id()
        )
        emit_event(
            event=EVENT_LLM_REQUEST,
            component=COMPONENT_LLM,
            outcome="started",
            correlation_id=effective_correlation_id,
        )
        recorder = _current_llm_timing_recorder()
        recorder.on_requested()
        started = self._clock()
        status_code: int | None = None
        body = ""
        try:
            _emit_llm_transport_phase(
                phase="request_started",
                elapsed_ms=0,
                http_status=None,
                response_bytes=None,
                correlation_id=effective_correlation_id,
            )
            response = self._post(payload)
            _emit_llm_transport_phase(
                phase="response_received",
                elapsed_ms=int((self._clock() - started) * 1000),
                http_status=getattr(response, "status_code", None),
                response_bytes=None,
                correlation_id=effective_correlation_id,
            )
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
            _emit_llm_transport_phase(
                phase="json_extracted",
                elapsed_ms=int((self._clock() - started) * 1000),
                http_status=int(status_code) if status_code is not None else None,
                response_bytes=len(body.encode("utf-8")) if body else 0,
                correlation_id=effective_correlation_id,
            )
            result = self._parse(body)
            _emit_llm_transport_phase(
                phase="result_parsed",
                elapsed_ms=int((self._clock() - started) * 1000),
                http_status=int(status_code) if status_code is not None else None,
                response_bytes=len(body.encode("utf-8")) if body else 0,
                correlation_id=effective_correlation_id,
            )
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            recorder.on_finished(
                outcome="error",
                finished_at=datetime.now(tz=timezone.utc),
            )
            emit_event(
                event=EVENT_LLM_REQUEST,
                component=COMPONENT_LLM,
                failure_category="http_error",
                http_status=int(status_code) if status_code is not None else None,
                exception_type="QueryLlmHttpError",
                elapsed_ms=int((self._clock() - started) * 1000),
                correlation_id=effective_correlation_id,
            )
            raise QueryLlmHttpError(status_code or 0, str(exc)) from exc
        except QueryLlmTimeoutError as exc:
            recorder.on_finished(
                outcome="timeout",
                finished_at=datetime.now(tz=timezone.utc),
            )
            emit_event(
                event=EVENT_LLM_REQUEST,
                component=COMPONENT_LLM,
                failure_category="timeout",
                exception_type=type(exc).__name__,
                elapsed_ms=int((self._clock() - started) * 1000),
                correlation_id=effective_correlation_id,
            )
            elapsed = self._clock() - started
            logger.error("llm request failure duration=%s", elapsed)
            raise
        except QueryLlmConnectionError as exc:
            recorder.on_finished(
                outcome="error",
                finished_at=datetime.now(tz=timezone.utc),
            )
            emit_event(
                event=EVENT_LLM_REQUEST,
                component=COMPONENT_LLM,
                failure_category="connection",
                exception_type=type(exc).__name__,
                elapsed_ms=int((self._clock() - started) * 1000),
                correlation_id=effective_correlation_id,
            )
            elapsed = self._clock() - started
            logger.error("llm request failure duration=%s", elapsed)
            raise
        except QueryLlmResponseError as exc:
            recorder.on_finished(
                outcome="error",
                finished_at=datetime.now(tz=timezone.utc),
            )
            emit_event(
                event=EVENT_LLM_REQUEST,
                component=COMPONENT_LLM,
                failure_category="response_error",
                exception_type=type(exc).__name__,
                elapsed_ms=int((self._clock() - started) * 1000),
                correlation_id=effective_correlation_id,
            )
            elapsed = self._clock() - started
            logger.error("llm request failure duration=%s", elapsed)
            raise
        except QueryLlmError:
            recorder.on_finished(
                outcome="error",
                finished_at=datetime.now(tz=timezone.utc),
            )
            elapsed = self._clock() - started
            logger.error("llm request failure duration=%s", elapsed)
            raise
        except Exception as exc:
            recorder.on_finished(
                outcome="error",
                finished_at=datetime.now(tz=timezone.utc),
            )
            emit_event(
                event=EVENT_LLM_REQUEST,
                component=COMPONENT_LLM,
                failure_category="unexpected",
                exception_type=type(exc).__name__,
                elapsed_ms=int((self._clock() - started) * 1000),
                correlation_id=effective_correlation_id,
            )
            elapsed = self._clock() - started
            logger.error("llm request failure duration=%s", elapsed)
            raise QueryLlmError(str(exc)) from exc
        elapsed = self._clock() - started
        logger.info(
            "llm request success duration=%s status=%s response_length=%s",
            elapsed,
            status_code,
            len(body),
        )
        recorder.on_finished(
            outcome="completed",
            finished_at=datetime.now(tz=timezone.utc),
        )
        emit_event(
            event=EVENT_LLM_REQUEST,
            component=COMPONENT_LLM,
            outcome="completed",
            elapsed_ms=int(elapsed * 1000),
            http_status=int(status_code) if status_code is not None else None,
            correlation_id=effective_correlation_id,
        )
        return result


__all__ = [
    "LLMTimingRecorder",
    "NoopLLMTimingRecorder",
    "QueryLlm",
    "QueryLlmConnectionError",
    "QueryLlmError",
    "QueryLlmHttpError",
    "QueryLlmResponseError",
    "QueryLlmTimeoutError",
    "WorkItemLLMTimingRecorder",
    "current_llm_correlation_id",
    "install_llm_timing_recorder",
    "reset_llm_timing_recorder",
]
