import json
import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from typing import Any, cast

import httpx
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
    chunk_count: int | None = None,
) -> None:
    """Emit one bounded ``llm_request_transport_phase`` observation.

    The diagnostic helper is the safe seam the
    :class:`QueryLlm` boundary uses to surface the last client-side
    transport phase reached during a request/response cycle. The
    payload is allowlist-bounded and privacy-safe by construction:
    only the closed phase token, bounded elapsed milliseconds,
    optional bounded HTTP status, optional bounded response byte
    count, optional bounded chunk count and the existing opaque
    correlation identifier are permitted. No prompt, response body,
    URL, proxy value, header, credential or exception text is ever
    included.

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
            chunk_count=chunk_count,
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


def _classify_post_exception(
    exc: BaseException,
    *,
    timeout_seconds: float,
) -> QueryLlmError:
    """Map a Requests exception to its canonical ``QueryLlmError``.

    The helper centralizes the mapping the boundary has used since
    before the diagnostic phases were introduced so the initial
    ``requests.post`` call and the subsequent ``iter_content``
    reading classify the same Requests failure mode into the same
    :class:`QueryLlmError` subtype. The classification is
    deliberate and matches the historical contract:

    * ``requests.exceptions.Timeout`` (which subsumes
      ``ReadTimeout``; ``ConnectTimeout`` is also a ``Timeout``
      subclass) → ``QueryLlmTimeoutError``.
    * ``requests.exceptions.ConnectionError`` (which subsumes
      ``ProxyError`` and ``SSLError``) →
      ``QueryLlmConnectionError``. A read timeout that Requests
      surfaces as a wrapped ``ConnectionError`` therefore still
      classifies consistently with the previous contract.
    * ``requests.exceptions.ChunkedEncodingError`` is the form
      Requests uses for an invalid chunked-encoding response,
      including the read-timeout-during-streaming shape the
      caller wants classified deliberately. Newer requests
      versions promote it to a direct ``RequestException``
      subclass (no longer a ``ConnectionError``); the explicit
      check keeps the mapping consistent across versions and
      consistent with the historical contract that wrapped
      ``ChunkedEncodingError`` as a ``ConnectionError``.

    The helper returns the mapped exception; the caller MUST
    ``raise ... from exc`` to preserve the chained traceback.
    The original exception is re-raised unchanged when the type
    does not match the closed Requests failure modes the
    boundary classifies (e.g. ``HTTPError`` is handled separately
    upstream and must not be wrapped into a timeout/connection
    error).
    """
    if isinstance(exc, requests.exceptions.Timeout):
        return QueryLlmTimeoutError(
            f"LLM request timed out after {timeout_seconds}s"
        )
    if isinstance(exc, requests.exceptions.ChunkedEncodingError):
        return QueryLlmConnectionError(f"LLM connection error: {exc}")
    if isinstance(exc, requests.exceptions.ConnectionError):
        return QueryLlmConnectionError(f"LLM connection error: {exc}")
    raise exc


def _translate_httpx_exception(
    exc: BaseException,
) -> requests.exceptions.RequestException:
    """Map a synchronous :mod:`httpx` exception to its Requests sibling.

    The translation keeps the established
    :func:`_classify_post_exception` mapper authoritative so the
    :class:`QueryLlm` boundary reports the same closed technical
    errors for both transports. The mapping is deliberately narrow:

    * ``httpx.TimeoutException`` (which subsumes ``ConnectTimeout``,
      ``ReadTimeout``, ``WriteTimeout`` and ``PoolTimeout``) →
      :class:`requests.exceptions.Timeout`.
    * every other :class:`httpx.HTTPError` (network, proxy, stream
      and protocol errors — including ``ConnectError``,
      ``ProxyError``, ``NetworkError``, ``RemoteProtocolError`` and
      ``ReadError``) and the streaming-only
      :class:`httpx.StreamError` (which is not a
      ``HTTPError`` subclass despite being a connection failure)
      → :class:`requests.exceptions.ConnectionError`, matching
      the historical Requests branch that classified ``ProxyError``,
      ``SSLError`` and ``ChunkedEncodingError`` as connection
      failures.

    The original exception is re-raised unchanged when its type
    does not match the closed HTTPX failure modes the boundary
    classifies (HTTP-status errors are handled separately by the
    :class:`_HttpxResponseAdapter` and never reach this helper).
    """
    if isinstance(exc, httpx.TimeoutException):
        return requests.exceptions.Timeout(str(exc))
    if isinstance(exc, httpx.HTTPError):
        return requests.exceptions.ConnectionError(str(exc))
    if isinstance(exc, httpx.StreamError):
        return requests.exceptions.ConnectionError(str(exc))
    raise exc


class _HttpxResponseAdapter:
    """Bridge an :class:`httpx.Response` to the ``requests.Response``-shaped
    interface :meth:`QueryLlm.request` already consumes.

    The adapter is intentionally narrow:

    * ``status_code``, ``text``, ``json()`` and ``close()`` are
      delegated verbatim so the surrounding :class:`QueryLlm`
      flow keeps reading the same attributes.
    * :meth:`iter_content` yields bytes from the underlying
      :meth:`httpx.Response.iter_bytes` and translates mid-stream
      transport / protocol / read-timeout failures into the
      :mod:`requests.exceptions` siblings the existing
      :func:`_classify_post_exception` mapper already understands.
    * :meth:`raise_for_status` raises
      :class:`requests.exceptions.HTTPError` (with the adapter
      attached as the ``response`` attribute, the exact pattern
      the existing tests already exercise) so the :class:`QueryLlm`
      HTTP-error branch keeps working unchanged.

    The adapter keeps a reference to the underlying
    :class:`httpx.Client` and closes both the response stream and
    the client pool on :meth:`close` — the client must outlive the
    ``client.send(stream=True)`` call so the streaming body
    iteration that :meth:`QueryLlm.request` performs after
    :meth:`_post_httpx` returns still has a live connection pool to
    drain.
    """

    def __init__(
        self,
        response: httpx.Response,
        client: httpx.Client,
    ) -> None:
        self._response = response
        self._client = client
        self.status_code = int(response.status_code)
        self.closed = False

    @property
    def text(self) -> str:
        return self._response.text

    def json(self) -> Any:
        return self._response.json()

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            err = requests.exceptions.HTTPError(
                f"{self.status_code} HTTP Error"
            )
            # The ``HTTPError.response`` attribute is typed as a
            # real :class:`requests.Response`, but the QueryLlm
            # boundary has always treated it as the duck-typed
            # response object that raised the error. The cast
            # keeps the existing ``exc.response.status_code``
            # access in :meth:`QueryLlm.request` working without
            # rebuilding the requests-shaped contract.
            err.response = cast(Any, self)
            raise err

    def iter_content(self, chunk_size: int = 8192):
        try:
            yield from self._response.iter_bytes(chunk_size)
        except (httpx.HTTPError, httpx.StreamError) as exc:
            raise _translate_httpx_exception(exc) from exc

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            try:
                self._client.close()
            finally:
                self.closed = True


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
            if self._settings.llm_http_client == "httpx":
                return self._post_httpx(payload)
            return self._post_requests(payload)
        except requests.exceptions.RequestException as exc:
            raise _classify_post_exception(
                exc, timeout_seconds=self._settings.llm_timeout
            ) from exc

    def _post_requests(self, payload: Mapping[str, Any]) -> Any:
        """Issue the historical Requests streaming POST.

        Preserved verbatim so the existing default transport and
        test seam keep behaving identically when ``LLM_HTTP_CLIENT``
        is absent or explicitly ``requests``.
        """
        return requests.post(
            self._settings.llm_url,
            json=payload,
            timeout=self._settings.llm_timeout,
            stream=True,
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

    def _post_httpx(self, payload: Mapping[str, Any]) -> Any:
        """Issue exactly one synchronous HTTPX streaming POST.

        The helper preserves the existing URL, the non-streaming
        Ollama payload (``stream: false`` is sent verbatim), the
        total ``LLM_TIMEOUT`` budget and the optional
        ``OLLAMA_PROXY_URL`` scope. The proxy URL is forwarded
        unchanged so httpcore honours the historical
        ``socks5://`` and ``socks5h://`` contract — the underlying
        ``Socks5Connection`` resolves the target with the same
        address type ``socksio`` already negotiates, and an IP
        literal is sent to the proxy as-is while a domain name is
        always forwarded as ``DOMAIN_NAME`` (i.e. remote DNS
        resolution). The proxy is therefore never downgraded to
        direct traffic and never leaks into a process-wide
        ``HTTP_PROXY`` environment variable.

        The helper never invokes :mod:`requests` and never falls
        back to the Requests transport on failure — a single
        HTTPX attempt is the only network operation it performs.
        The returned adapter keeps a reference to the live
        :class:`httpx.Client` so the streaming body iteration
        :meth:`request` performs next still has a live connection
        pool to drain; both the response stream and the client are
        closed when the adapter's :meth:`close` runs from the
        surrounding :meth:`request` ``finally`` block.
        """
        proxy = self._settings.ollama_proxy_url
        timeout = self._settings.llm_timeout
        client_kwargs: dict[str, Any] = {"timeout": timeout}
        if proxy is not None:
            client_kwargs["proxy"] = proxy
        client = httpx.Client(**client_kwargs)
        try:
            try:
                request = client.build_request(
                    "POST",
                    self._settings.llm_url,
                    json=payload,
                )
                response = client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise _translate_httpx_exception(exc) from exc
        except BaseException:
            client.close()
            raise
        return _HttpxResponseAdapter(response=response, client=client)

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
        response = None
        body_bytes_count = 0
        chunk_count = 0
        try:
            _emit_llm_transport_phase(
                phase="request_started",
                elapsed_ms=0,
                http_status=None,
                response_bytes=None,
                correlation_id=effective_correlation_id,
            )
            response = self._post(payload)
            status_code = getattr(response, "status_code", None)
            _emit_llm_transport_phase(
                phase="response_headers_received",
                elapsed_ms=int((self._clock() - started) * 1000),
                http_status=int(status_code) if status_code is not None else None,
                response_bytes=None,
                correlation_id=effective_correlation_id,
            )
            iter_content = getattr(response, "iter_content", None)
            if callable(iter_content):
                iter_content_fn = cast(
                    Callable[..., Iterator[bytes]], iter_content
                )
                # Streaming path: real ``requests.Response`` returns
                # after headers are available. ``stream=True`` keeps
                # the Ollama payload ``stream: false`` (the LLM server
                # side still emits a single JSON envelope); we read it
                # incrementally here only to observe the receipt
                # boundary, never to enable Ollama NDJSON streaming.
                response.raise_for_status()
                body_chunks: list[bytes] = []
                try:
                    for chunk in iter_content_fn(chunk_size=8192):
                        if not chunk:
                            continue
                        body_chunks.append(chunk)
                        body_bytes_count += len(chunk)
                        chunk_count += 1
                        if chunk_count == 1:
                            _emit_llm_transport_phase(
                                phase="first_body_chunk",
                                elapsed_ms=int(
                                    (self._clock() - started) * 1000
                                ),
                                http_status=(
                                    int(status_code)
                                    if status_code is not None
                                    else None
                                ),
                                response_bytes=None,
                                chunk_count=chunk_count,
                                correlation_id=effective_correlation_id,
                            )
                except requests.exceptions.RequestException as exc:
                    raise _classify_post_exception(
                        exc, timeout_seconds=self._settings.llm_timeout
                    ) from exc
                body_bytes = b"".join(body_chunks)
                try:
                    envelope_text = body_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    envelope_text = body_bytes.decode(
                        "utf-8", errors="replace"
                    )
                # Reconstruct the same inner response the prior
                # ``response.json()`` extraction produced. The
                # classification mirrors the legacy contract:
                #   * envelope JSON dict → ``envelope_data["response"]``
                #   * envelope JSON valid non-dict (``[]``, ``null``,
                #     number, string) → ``body = ""`` so the
                #     subsequent ``_parse`` raises
                #     ``QueryLlmResponseError``, exactly as the old
                #     ``body = "" if not isinstance(data, dict) else ...``
                #     branch behaved. The classification deliberately
                #     distinguishes a non-decodable envelope from a
                #     JSON ``null`` envelope so a malformed Ollama
                #     response cannot silently succeed as ``None``.
                #   * envelope not JSON-decodable → fall back to the
                #     raw envelope text so ``_parse`` can recover the
                #     first balanced JSON object, matching the
                #     previous ``ValueError`` fallback that fed
                #     ``response.text`` back into ``_parse``.
                if envelope_text:
                    try:
                        envelope_data: Any = json.loads(envelope_text)
                        envelope_decoded = True
                    except json.JSONDecodeError:
                        envelope_data = None
                        envelope_decoded = False
                else:
                    envelope_data = None
                    envelope_decoded = False
                if envelope_decoded and isinstance(envelope_data, dict):
                    body = envelope_data.get("response") or ""
                elif not envelope_decoded:
                    body = envelope_text
                else:
                    body = ""
            else:
                # Eager adapter seam: an injected ``transport`` stub
                # returns a complete response without ``iter_content``.
                # Mirror the previous eager read so the existing test
                # stubs continue to work without a second business
                # path; the final string handed to ``_parse`` is the
                # same as ``response.text`` would have produced. The
                # non-dict branch mirrors the streaming path: a valid
                # JSON envelope that is not an object becomes an empty
                # body so ``_parse`` raises ``QueryLlmResponseError``,
                # equivalent to the legacy ``response.json()`` call.
                response.raise_for_status()
                try:
                    data = response.json()
                except ValueError:
                    data = {"response": getattr(response, "text", "")}
                if isinstance(data, dict):
                    body = data.get("response") or ""
                else:
                    body = ""
                body_bytes_count = len(body.encode("utf-8"))
                chunk_count = 1 if body else 0
                if chunk_count > 0:
                    _emit_llm_transport_phase(
                        phase="first_body_chunk",
                        elapsed_ms=int((self._clock() - started) * 1000),
                        http_status=(
                            int(status_code)
                            if status_code is not None
                            else None
                        ),
                        response_bytes=None,
                        chunk_count=chunk_count,
                        correlation_id=effective_correlation_id,
                    )
            _emit_llm_transport_phase(
                phase="body_completed",
                elapsed_ms=int((self._clock() - started) * 1000),
                http_status=int(status_code) if status_code is not None else None,
                response_bytes=body_bytes_count,
                chunk_count=chunk_count,
                correlation_id=effective_correlation_id,
            )
            _emit_llm_transport_phase(
                phase="response_received",
                elapsed_ms=int((self._clock() - started) * 1000),
                http_status=int(status_code) if status_code is not None else None,
                response_bytes=body_bytes_count,
                correlation_id=effective_correlation_id,
            )
            _emit_llm_transport_phase(
                phase="json_extracted",
                elapsed_ms=int((self._clock() - started) * 1000),
                http_status=int(status_code) if status_code is not None else None,
                response_bytes=body_bytes_count,
                correlation_id=effective_correlation_id,
            )
            result = self._parse(body)
            _emit_llm_transport_phase(
                phase="result_parsed",
                elapsed_ms=int((self._clock() - started) * 1000),
                http_status=int(status_code) if status_code is not None else None,
                response_bytes=body_bytes_count,
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
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    logger.exception("llm_response_close_failed")
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
