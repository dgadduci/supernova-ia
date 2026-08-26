import json
import logging
import threading
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from typing import Any, cast

import httpx
import requests
from requests.adapters import HTTPAdapter
from urllib3.contrib.socks import (
    SOCKSConnection,
    SOCKSHTTPConnectionPool,
    SOCKSHTTPSConnection,
    SOCKSHTTPSConnectionPool,
    SOCKSProxyManager,
)

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


class _SocksPhaseObserverMixin:
    """Mixin that emits the closed SOCKS / HTTP-writer phase events
    around the existing seams.

    The mixin is private to :mod:`backend.llm.query_llm` and only
    participates in the QueryLlm default Requests path when the
    configured ``OLLAMA_PROXY_URL`` selects the SOCKS scheme. Two
    hooks from the supported, pinned urllib3 / PySocks stack are
    wrapped:

    * ``_new_conn()`` is the existing SOCKS connect / negotiation
      seam (delegates to ``socks.create_connection`` and the existing
      PySocks handshake). The start event is emitted on entry and the
      completion event only after a usable socket has been returned.
      A blocked or failed seam therefore never fabricates the
      completion event.
    * ``request()`` is the existing HTTP request writer (the single
      call that hands request bytes to the socket layer via
      ``putrequest`` / ``putheader`` / ``endheaders`` / ``send``).
      The start event is emitted on entry and the completion event
      only after the writer returned successfully. A blocked or
      failed write never fabricates the completion event and never
      leaks there because ``requests.post`` already classifies the
      underlying exception through the unchanged
      :func:`_classify_post_exception` mapper.

    The mixin mirrors the real stack order:
    ``request_write_started`` is emitted when the inherited writer is
    entered; ``http.client.HTTPConnection.send`` then lazily invokes
    :meth:`connect` (which routes through
    :class:`SOCKSConnection._new_conn`) so the SOCKS pair fires only
    after the writer has already been entered; the SOCKS pair is
    followed by ``request_write_completed`` once the writer returns.
    When the same connection already has a cached socket the lazy
    connect step is skipped, the SOCKS pair is omitted (and never
    fabricated) and only the writer pair fires. The mixin never
    forces DNS, TCP, SOCKS, TLS or the target connection ahead of
    the stack's lazy ordering, never duplicates the connection, the
    writer or the request, and never mutates business state.

    The mixin never raises from the observation helper itself: the
    existing ``_emit_llm_transport_phase`` helper swallows emitter
    failures and the new helper additionally guards against any
    unexpected attribute / clock error so a misconfigured observer
    cannot duplicate the request, the writer or the connection.
    The helper never logs URL, host, IP, port, proxy, credential,
    SOCKS bytes, headers, prompt, body, response text, exception
    text or traceback and never mutates business state.
    """

    def _new_conn(self):  # type: ignore[override]
        _emit_socks_phase_observation(
            "socks_connect_started",
            elapsed_ms=0,
        )
        _socks_seam_clock = __import__("time").monotonic
        started = _socks_seam_clock()
        connected = super()._new_conn()  # type: ignore[misc]
        _emit_socks_phase_observation(
            "socks_connect_completed",
            elapsed_ms=_bounded_elapsed_ms(_socks_seam_clock() - started),
        )
        return connected

    def request(  # type: ignore[override]
        self,
        method: str,
        url: str,
        body: Any = None,
        headers: Any = None,
        *,
        chunked: bool = False,
        preload_content: bool = True,
        decode_content: bool = True,
        enforce_content_length: bool = True,
    ) -> None:
        # The stack is lazy: ``http.client.HTTPConnection.send`` invokes
        # :meth:`connect` on demand, which routes through
        # :class:`SOCKSConnection._new_conn` for the SOCKS scheme. The
        # mixin therefore observes the real order
        # (``request_write_started`` → ``socks_connect_started`` →
        # ``socks_connect_completed`` (only on return) →
        # ``request_write_completed`` (only on return)). Forcing
        # :meth:`connect` ahead of the writer would only invert the
        # real stack order and pre-allocate a socket the writer is
        # perfectly capable of opening lazily, so the seam must not
        # touch ``self.connect`` here. When the same connection
        # already has a cached socket the SOCKS pair is omitted and
        # only the writer pair fires.
        _emit_socks_phase_observation(
            "request_write_started",
            elapsed_ms=0,
        )
        _writer_clock = __import__("time").monotonic
        started = _writer_clock()
        super().request(  # type: ignore[misc]
            method,
            url,
            body=body,
            headers=headers,
            chunked=chunked,
            preload_content=preload_content,
            decode_content=decode_content,
            enforce_content_length=enforce_content_length,
        )
        _emit_socks_phase_observation(
            "request_write_completed",
            elapsed_ms=_bounded_elapsed_ms(_writer_clock() - started),
        )


class _ObservingSocksHTTPConnection(
    _SocksPhaseObserverMixin, SOCKSConnection
):
    """Plain HTTP SOCKS connection with the observer mixin applied.

    The class is wired to :class:`_ObservingSocksHTTPConnectionPool`
    so the existing urllib3 ``SOCKSHTTPConnectionPool`` keeps
    driving it. Only the two observed seams are wrapped; every other
    inherited attribute (``host``, ``port``, ``timeout``,
    ``_socks_options``, ``_tunnel_host`` / ``_tunnel_port`` /
    ``_tunnel_scheme``) is delegated unchanged.
    """


class _ObservingSocksHTTPSConnection(
    _SocksPhaseObserverMixin, SOCKSHTTPSConnection
):
    """HTTPS SOCKS connection with the observer mixin applied.

    Mirrors :class:`_ObservingSocksHTTPConnection` for the TLS
    scheme. The mixin method-resolution order ensures ``_new_conn``
    still routes through :class:`SOCKSConnection._new_conn`
    (SOCKSHTTPSConnection does not redefine it) and ``request``
    still routes through :class:`HTTPConnection.request`, so the
    TLS handshake and the body writer stay on the existing pinned
    code paths.
    """


class _ObservingSocksHTTPConnectionPool(SOCKSHTTPConnectionPool):
    """Plain HTTP SOCKS pool wired to
    :class:`_ObservingSocksHTTPConnection`.

    Only the connection class is swapped; everything else (pool
    sizing, retry, headers, host routing) is delegated unchanged.
    """

    ConnectionCls = _ObservingSocksHTTPConnection


class _ObservingSocksHTTPSConnectionPool(SOCKSHTTPSConnectionPool):
    """HTTPS SOCKS pool wired to
    :class:`_ObservingSocksHTTPSConnection`.

    Mirrors :class:`_ObservingSocksHTTPConnectionPool` for the TLS
    scheme. The TLS handshake itself is delegated to the existing
    urllib3 / PySocks path; the class only observes the wrapped
    :meth:`SOCKSConnection._new_conn` seam.
    """

    ConnectionCls = _ObservingSocksHTTPSConnection


class _ObservingSocksProxyManager(SOCKSProxyManager):
    """SOCKS proxy manager that routes every pool through the observing
    connection class.

    Only ``pool_classes_by_scheme`` is overridden; the parsed proxy
    options, username / password extraction, pool sizing and all
    other behaviour come from the existing
    :class:`SOCKSProxyManager` base class. The :meth:`__init__` mirror
    is required because :class:`SOCKSProxyManager.__init__` rewrites
    ``pool_classes_by_scheme`` to the base mapping after
    ``super().__init__`` runs, so a class-level override alone would
    be silently discarded.
    """

    pool_classes_by_scheme = {  # noqa: RUF012 - mirrors SOCKSProxyManager
        "http": _ObservingSocksHTTPConnectionPool,
        "https": _ObservingSocksHTTPSConnectionPool,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pool_classes_by_scheme = _ObservingSocksProxyManager.pool_classes_by_scheme


class _ObservingSocksAdapter(HTTPAdapter):
    """Adapter that wires :class:`_ObservingSocksProxyManager` for SOCKS
    proxy URLs only.

    Non-SOCKS proxies continue to use the historical
    :class:`HTTPAdapter.proxy_manager_for` path so the change is
    fully backward compatible and never touches the no-proxy or the
    HTTPX branches. The adapter caches the proxy manager by URL the
    same way the parent does, so repeated calls reuse the same
    observing pool.
    """

    def proxy_manager_for(self, proxy, **proxy_kwargs):  # type: ignore[override]
        if proxy in self.proxy_manager:
            return self.proxy_manager[proxy]
        if proxy.lower().startswith("socks"):
            username, password = requests.utils.get_auth_from_url(proxy)
            manager: Any = _ObservingSocksProxyManager(
                proxy,
                username=username,
                password=password,
                num_pools=self._pool_connections,
                maxsize=self._pool_maxsize,
                block=self._pool_block,
                **proxy_kwargs,
            )
            self.proxy_manager[proxy] = manager
            return manager
        return super().proxy_manager_for(proxy, **proxy_kwargs)


class _SocksPhaseObserverSession(requests.Session):
    """Private Session that mounts :class:`_ObservingSocksAdapter` for
    every URL scheme.

    The adapter only activates for SOCKS proxy URLs; non-SOCKS
    traffic goes through the standard :class:`HTTPAdapter` path.
    The session is constructed per-call by
    :meth:`QueryLlm._post_requests` when the configured
    ``OLLAMA_PROXY_URL`` selects the SOCKS scheme so two consecutive
    requests never share a session, an adapter, a proxy manager, a
    connection pool or a socket. The session lives only as long as
    the single request it serves; the surrounding
    :meth:`QueryLlm.request` ``finally`` block closes the response
    through :class:`_SocksResponseSessionCloser`, which closes
    both the response and its private session exactly once.
    """

    def __init__(self) -> None:
        super().__init__()
        adapter = _ObservingSocksAdapter()
        self.mount("http://", adapter)
        self.mount("https://", adapter)


def _is_socks_proxy_url(proxy_url: Any) -> bool:
    """Return ``True`` when the proxy URL selects the SOCKS scheme.

    Mirrors the historical Requests / urllib3 prefix check so the
    observer is only applied to the SOCKS code path that already
    routes through :class:`SOCKSProxyManager`. ``None``, empty
    strings and non-SOCKS schemes resolve to ``False`` so the
    no-proxy, injected-transport, HTTPX and non-SOCKS proxy
    branches continue to use the historical ``requests.post``
    call site unchanged.
    """
    if not isinstance(proxy_url, str):
        return False
    if not proxy_url:
        return False
    return proxy_url.lower().startswith("socks")


class _SocksResponseSessionCloser:
    """Wrapper that delegates every attribute to the wrapped
    ``requests.Response`` and closes both the response and its
    private :class:`_SocksPhaseObserverSession` exactly once when
    the surrounding :meth:`QueryLlm.request` ``finally`` block
    closes the response.

    The wrapper is intentionally fail-soft and silent: a
    ``close()`` failure on the response or the session is swallowed
    without logging so the surrounding business flow cannot crash
    because of the observability seam and no traceback, exception
    text or sensitive value can leak through the diagnostic channel.
    The wrapper never reopens the session, never duplicates the
    response, never logs URL / host / IP / port / proxy /
    credential / SOCKS bytes / headers / prompt / body / response
    text / exception text / traceback and never mutates business
    state. Two consecutive wrappers over different requests are
    independent objects, so closing one cannot affect the other.
    """

    def __init__(
        self,
        *,
        response: requests.Response,
        session: requests.Session,
    ) -> None:
        self._response = response
        self._session = session
        self._closed = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self._response, name)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._response.close()
        except Exception:  # noqa: BLE001, S110 - silent fail-soft by privacy contract
            pass
        try:
            self._session.close()
        except Exception:  # noqa: BLE001, S110 - silent fail-soft by privacy contract
            pass


def _bounded_elapsed_ms(seconds: float) -> int:
    """Convert a monotonically non-negative elapsed time into the
    closed ``[0, _MAX_ELAPSED_MS]`` integer range the
    ``llm_request_transport_phase`` validator enforces.

    The helper is a local duplicate of the closed contract used by
    :mod:`backend.observability.events` so the urllib3 layer cannot
    leak a Python float or an out-of-range value into the event.
    """
    try:
        elapsed = int(seconds * 1000)
    except (TypeError, ValueError, OverflowError):
        return 0
    if elapsed < 0:
        return 0
    if elapsed > 24 * 60 * 60 * 1000:
        return 24 * 60 * 60 * 1000
    return elapsed


def _emit_socks_phase_observation(
    phase: str,
    *,
    elapsed_ms: int,
) -> None:
    """Emit one bounded SOCKS / writer observation.

    The helper mirrors the safe-emission pattern used by
    :func:`_emit_llm_transport_phase` and never raises so a
    misconfigured emitter cannot duplicate the connection, the
    writer or the request. The correlation value is read from the
    existing thread-local installed by the provider coordinator so
    every observation shares the same opaque synthetic inbound
    identifier as the surrounding ``llm_request`` event. The phase
    payload is privacy-safe by construction: no URL, host, IP,
    port, proxy, credential, SOCKS handshake byte, header, prompt,
    body, response text, exception text or traceback is included.

    Emission failures are swallowed silently to honour the change's
    privacy contract: no traceback, no ``logger.exception``, no
    interpolation of the exception or its arguments, URL, host,
    proxy, credential, header, payload or any other sensitive
    value is allowed on this code path. A misconfigured emitter
    MUST never duplicate the connection, the writer or the
    request, and MUST never leak diagnostic context through the
    logging seam.
    """
    try:
        correlation_id = _current_llm_correlation_id()
        emit_event(
            event=EVENT_LLM_REQUEST_TRANSPORT_PHASE,
            component=COMPONENT_LLM,
            phase=phase,
            elapsed_ms=elapsed_ms,
            http_status=None,
            response_bytes=None,
            chunk_count=None,
            correlation_id=correlation_id,
        )
    except Exception:  # noqa: BLE001, S110 - silent fail-soft by privacy contract
        pass


def _close_socks_session_safely(session: requests.Session) -> None:
    """Close a SOCKS observer session exactly once, swallowing all
    errors silently.

    The helper is the safe companion of
    :class:`_SocksResponseSessionCloser` used when ``session.post``
    itself raises and there is no response wrapper to drive the
    close path. It honours the same fail-soft, silent contract:
    no ``logger.exception``, no ``exc_info``, no interpolation of
    the exception or its arguments, URL, host, proxy, credential,
    header, payload or any other sensitive value. A close failure
    is dropped because the original exception raised by
    ``session.post`` is the one the surrounding
    :meth:`QueryLlm.request` flow is expected to classify; the
    diagnostic seam MUST NOT mask, alter or substitute it.
    """
    try:
        session.close()
    except Exception:  # noqa: BLE001, S110 - silent fail-soft by privacy contract
        pass


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

        When the configured ``OLLAMA_PROXY_URL`` selects the SOCKS
        scheme the call is routed through a private
        :class:`_SocksPhaseObserverSession` constructed per-request
        so the existing SOCKS connect seam
        (``urllib3.contrib.socks.SOCKSConnection._new_conn``) and the
        existing HTTP writer seam (``HTTPConnection.request``) emit
        the closed SOCKS-boundary phases around their returns. A
        fresh session / adapter / proxy manager / connection pool is
        built on every call so two consecutive SOCKS requests never
        share a session, a pool, an adapter, a manager or a socket.
        The response is wrapped with
        :class:`_SocksResponseSessionCloser` so the surrounding
        :meth:`QueryLlm.request` ``finally`` block closes both the
        response and its private session exactly once. The
        non-SOCKS proxy and no-proxy branches continue to use
        ``requests.post`` verbatim so the change is fully backward
        compatible.
        """
        proxy_url = self._settings.ollama_proxy_url
        if _is_socks_proxy_url(proxy_url):
            session = _SocksPhaseObserverSession()
            try:
                response = session.post(
                    self._settings.llm_url,
                    json=payload,
                    timeout=self._settings.llm_timeout,
                    stream=True,
                    proxies={  # type: ignore[arg-type]
                        "http": proxy_url,
                        "https": proxy_url,
                    },
                )
            except BaseException:
                # ``session.post`` can raise ``Timeout``,
                # ``ConnectionError``, ``ProxyError`` or any other
                # :mod:`requests.exceptions.RequestException` while
                # there is no response to wrap; the private
                # observer session MUST still be closed exactly
                # once to honour the per-request lifecycle. The
                # original exception is re-raised unchanged so the
                # existing ``_classify_post_exception`` mapper in
                # :meth:`_post` keeps producing the canonical
                # ``QueryLlm*Error`` subtype and no second request,
                # no fabricated completion / header phases and no
                # response wrapper are produced.
                _close_socks_session_safely(session)
                raise
            return _SocksResponseSessionCloser(
                response=response, session=session
            )
        proxy_kwargs: dict[str, Any] = (
            {
                "proxies": {
                    "http": proxy_url,
                    "https": proxy_url,
                }
            }
            if proxy_url is not None
            else {}
        )
        return requests.post(
            self._settings.llm_url,
            json=payload,
            timeout=self._settings.llm_timeout,
            stream=True,
            **proxy_kwargs,
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
