"""Standalone diagnostic CLI for the Railway-local repeated HTTP transport.

Run inside the Railway ``supernova-ia`` service with::

    PYTHONPATH=. python -m backend.scripts.probe_railway_socks5_repeated

The diagnostic investigates whether intermittent request loss is associated
with repeated HTTP connection establishment at the local
``requests`` → ``socks5h://127.0.0.1:1055`` boundary. It deliberately sits
below :class:`backend.llm.query_llm.QueryLlm` so the operator can observe
the exact HTTP call shape without depending on the production transport
seam, the worker, the coordinator, the database, Twilio, Tailscale or
Ollama.

The diagnostic is side-effect-free at the application layer:

* it does NOT open a database session;
* it does NOT send any provider message, create any order, perform any
  retry, lease or outbox row;
* it does NOT mutate the service settings, environment variables or the
  configured LLM URL/proxy.

The diagnostic refuses to run when the configured SOCKS5 proxy URL is
missing or structurally invalid: in that case it emits a single bounded
``configuration_error`` record, returns exit code ``1`` and never builds
a direct request. A failure to load the service settings is also
captured as a bounded ``configuration_error`` record so the operator
output never leaks tracebacks.

The terminal output is allowlist-bounded: only the mode, attempt number,
UTC timestamps, elapsed milliseconds, bounded phase, bounded HTTP
status, bounded response byte count, a closed outcome token and a safe
exception class or category are printed. The target URL, proxy URL,
request body, response body, headers, credentials, customer/order data,
exception text and tracebacks are NEVER printed.
"""
from __future__ import annotations

import argparse
import math
import sys
import time
import urllib.parse
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import requests

from backend.config.settings import Settings, load_settings

_MODE_FRESH = "fresh"
_MODE_SESSION = "session"
_ALLOWED_MODES: tuple[str, ...] = (_MODE_FRESH, _MODE_SESSION)

_DEFAULT_COUNT = 10
_DEFAULT_CONNECT_TIMEOUT_SECONDS = 5
_DEFAULT_READ_TIMEOUT_SECONDS = 20

# Allowed proxy URL schemes. The diagnostic is closed-bounded: a proxy
# URL outside this allowlist is treated as a configuration error and the
# request is never issued.
_ALLOWED_PROXY_SCHEMES: frozenset[str] = frozenset(
    {"socks5", "socks5h", "http", "https"}
)

# Closed outcome tokens. Anything outside this allowlist is replaced with
# ``request_error`` so the diagnostic never leaks the raw exception text.
_OUTCOME_SUCCESS = "success"
_OUTCOME_EMPTY_RESPONSE = "empty_response"
_OUTCOME_HTTP_STATUS = "http_status"
_OUTCOME_CONNECT_TIMEOUT = "connect_timeout"
_OUTCOME_READ_TIMEOUT = "read_timeout"
_OUTCOME_PROXY_ERROR = "proxy_error"
_OUTCOME_CONNECTION_ERROR = "connection_error"
_OUTCOME_REQUEST_ERROR = "request_error"
_OUTCOME_CONFIGURATION_ERROR = "configuration_error"

_PHASE_RETURNED = "returned"
_PHASE_EXCEPTION = "exception"

# Sentinel for an HTTP status that was not produced by the attempt.
_NO_HTTP_STATUS = "none"

# Synthetic attempt number used when the diagnostic aborts before any
# real attempt is made (e.g. configuration error). The value is a
# closed token that the formatter renders without leaking the original
# exception text or proxy value.
_CONFIGURATION_ERROR_ATTEMPT = 0
_CONFIGURATION_ERROR_DURATION_MS = 0


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as ISO-8601 with ``Z`` suffix."""

    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _resolve_positive_int(value: str, *, flag: str) -> int:
    """Validate a CLI flag that must be a positive integer."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{flag} must be a positive integer (got {value!r})"
        ) from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            f"{flag} must be a positive integer (got {parsed})"
        )
    return parsed


def _resolve_positive_finite_float(value: str, *, flag: str) -> float:
    """Validate a CLI flag that must be a positive finite number."""

    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{flag} must be a positive finite number (got {value!r})"
        ) from exc
    if math.isnan(parsed) or math.isinf(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(
            f"{flag} must be a positive finite number (got {parsed!r})"
        )
    return parsed


def _resolve_mode(value: str) -> str:
    if value not in _ALLOWED_MODES:
        raise argparse.ArgumentTypeError(
            f"--mode must be one of {', '.join(_ALLOWED_MODES)} (got {value!r})"
        )
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="probe_railway_socks5_repeated",
        description=(
            "Standalone diagnostic CLI that compares fresh requests.post "
            "against a single diagnostic requests.Session through the "
            "configured local SOCKS5 proxy. It prints only safe timing and "
            "transport metadata; URL, proxy, body, headers, credentials, "
            "exception text and tracebacks are never surfaced."
        ),
    )
    parser.add_argument(
        "--mode",
        type=_resolve_mode,
        choices=_ALLOWED_MODES,
        default=_MODE_FRESH,
        help=(
            "Call shape: 'fresh' uses top-level requests.post for every "
            "attempt (matching the current application shape); 'session' "
            "uses one diagnostic-only requests.Session for the bounded run."
        ),
    )
    parser.add_argument(
        "--count",
        type=lambda v: _resolve_positive_int(v, flag="--count"),
        default=_DEFAULT_COUNT,
        help=(
            "Number of sequential attempts (positive integer, "
            f"default {_DEFAULT_COUNT})."
        ),
    )
    parser.add_argument(
        "--connect-timeout-seconds",
        type=lambda v: _resolve_positive_finite_float(
            v, flag="--connect-timeout-seconds"
        ),
        default=_DEFAULT_CONNECT_TIMEOUT_SECONDS,
        help=(
            "Connect timeout in seconds (positive finite number, "
            f"default {_DEFAULT_CONNECT_TIMEOUT_SECONDS})."
        ),
    )
    parser.add_argument(
        "--read-timeout-seconds",
        type=lambda v: _resolve_positive_finite_float(
            v, flag="--read-timeout-seconds"
        ),
        default=_DEFAULT_READ_TIMEOUT_SECONDS,
        help=(
            "Read timeout in seconds (positive finite number, "
            f"default {_DEFAULT_READ_TIMEOUT_SECONDS})."
        ),
    )
    return parser


def _validate_proxy_url(proxy_url: Any) -> bool:
    """Return ``True`` if ``proxy_url`` is a structurally usable proxy URL.

    The check is allowlist-bounded: a missing, empty, non-string, or
    structurally invalid value (including unsupported schemes) is
    treated as a configuration error so the diagnostic never builds a
    direct request and never leaks the original value. The function
    NEVER raises and NEVER returns the URL itself.
    """

    if proxy_url is None:
        return False
    if not isinstance(proxy_url, str):
        return False
    stripped = proxy_url.strip()
    if not stripped:
        return False
    try:
        parsed = urllib.parse.urlparse(stripped)
    except (ValueError, TypeError, AttributeError):
        return False
    if not parsed.scheme or not parsed.hostname:
        return False
    return parsed.scheme.lower() in _ALLOWED_PROXY_SCHEMES


def _build_proxies(settings: Settings) -> dict[str, str]:
    """Return the proxy mapping loaded from :class:`Settings`.

    The returned mapping is the same shape :class:`requests` accepts as the
    ``proxies`` keyword argument. The values are NEVER printed by the
    diagnostic; the function only passes them through to
    :func:`requests.post` or :meth:`requests.Session.post`. Callers MUST
    validate the proxy URL with :func:`_validate_proxy_url` before
    invoking this function; the function is defensive and returns an
    empty mapping when the URL is missing or invalid so a stray caller
    cannot accidentally build a direct request.
    """

    proxy_url = settings.ollama_proxy_url
    if not isinstance(proxy_url, str) or not _validate_proxy_url(proxy_url):
        return {}
    return {"http": proxy_url, "https": proxy_url}


def _build_payload(settings: Settings) -> dict[str, Any]:
    """Build the bounded JSON payload using the configured model.

    The payload is NEVER printed or surfaced in any return value. The
    configured model name is forwarded so the request exercises the
    real LLM contract at the configured HTTP target; the prompt and
    stream flag are fixed, non-business tokens.
    """

    return {
        "model": settings.llm_model,
        "prompt": "ok",
        "stream": False,
    }


def _classify_exception(exc: BaseException) -> tuple[str, str]:
    """Map a Requests-style exception to a closed outcome and class label.

    The mapping is allowlist-bounded so a misconfigured exception cannot
    leak into the operator output. The function NEVER raises and NEVER
    exposes ``str(exc)`` or traceback content.
    """

    if isinstance(exc, requests.exceptions.ReadTimeout):
        return _OUTCOME_READ_TIMEOUT, type(exc).__name__
    if isinstance(exc, requests.exceptions.ConnectTimeout):
        return _OUTCOME_CONNECT_TIMEOUT, type(exc).__name__
    if isinstance(exc, requests.exceptions.ProxyError):
        return _OUTCOME_PROXY_ERROR, type(exc).__name__
    if isinstance(exc, requests.exceptions.ConnectionError):
        return _OUTCOME_CONNECTION_ERROR, type(exc).__name__
    if isinstance(exc, requests.exceptions.RequestException):
        return _OUTCOME_REQUEST_ERROR, type(exc).__name__
    return _OUTCOME_REQUEST_ERROR, type(exc).__name__


def _consume_and_close(response: Any) -> tuple[int | None, int]:
    """Read the response body and close it.

    Returns ``(status_code, received_bytes)``. The status code is taken
    from the live response object before closure so a non-2xx status can
    still be reported.
    """

    status_code = getattr(response, "status_code", None)
    received_bytes = 0
    try:
        content = getattr(response, "content", None)
        if content is not None:
            received_bytes = len(content)
            return status_code, received_bytes
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                received_bytes += len(chunk)
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    return status_code, received_bytes


def _format_attempt_line(record: dict[str, Any]) -> str:
    """Render the bounded one-line attempt record."""

    parts: list[str] = [
        f"mode={record['mode']}",
        f"attempt={record['attempt']}",
        f"inicio_utc={record['inicio_utc']}",
        f"fin_utc={record['fin_utc']}",
        f"duracion_ms={record['duracion_ms']}",
        f"phase={record['phase']}",
    ]
    if "http_status" in record:
        parts.append(f"http_status={record['http_status']}")
    else:
        parts.append(f"http_status={_NO_HTTP_STATUS}")
    if "received_bytes" in record:
        parts.append(f"received_bytes={record['received_bytes']}")
    else:
        parts.append("received_bytes=0")
    parts.append(f"outcome={record['outcome']}")
    if "exception_class" in record:
        parts.append(f"exception_class={record['exception_class']}")
    return " ".join(parts)


def _record_attempt(
    *,
    mode: str,
    attempt: int,
    started_mono: float,
    started_utc: str,
    phase: str,
    outcome: str,
    http_status: int | None,
    received_bytes: int | None,
    exception_class: str | None,
) -> tuple[str, dict[str, Any]]:
    """Build the bounded attempt record and its terminal one-line render."""

    finished_utc = _utc_now_iso()
    elapsed_ms = int((time.monotonic() - started_mono) * 1000)
    record: dict[str, Any] = {
        "mode": mode,
        "attempt": attempt,
        "inicio_utc": started_utc,
        "fin_utc": finished_utc,
        "duracion_ms": elapsed_ms,
        "phase": phase,
        "outcome": outcome,
    }
    if http_status is not None:
        record["http_status"] = int(http_status)
    if received_bytes is not None:
        record["received_bytes"] = int(received_bytes)
    if exception_class is not None:
        record["exception_class"] = exception_class
    return _format_attempt_line(record), record


def _record_configuration_error(mode: str) -> tuple[str, dict[str, Any]]:
    """Build a bounded ``configuration_error`` attempt record.

    The record contains no URL, proxy, exception, traceback or secret.
    It is the single record emitted when the service settings cannot be
    loaded or the configured proxy URL is missing/structurally invalid,
    so the operator output remains closed even on a broken environment.
    """

    now_utc = _utc_now_iso()
    record: dict[str, Any] = {
        "mode": mode,
        "attempt": _CONFIGURATION_ERROR_ATTEMPT,
        "inicio_utc": now_utc,
        "fin_utc": now_utc,
        "duracion_ms": _CONFIGURATION_ERROR_DURATION_MS,
        "phase": _PHASE_EXCEPTION,
        "outcome": _OUTCOME_CONFIGURATION_ERROR,
    }
    return _format_attempt_line(record), record


def _invoke_post(
    post_callable: Callable[..., Any],
    *,
    url: str,
    payload: dict[str, Any],
    timeout: tuple[float, float],
    proxies: dict[str, str],
) -> Any:
    """Invoke the configured ``requests.post`` call shape.

    The function forwards ``timeout`` as a tuple
    ``(connect_timeout, read_timeout)`` and ``proxies`` as a mapping so
    the diagnostic exercises the exact same keyword contract
    :class:`requests.post` expects.
    """

    return post_callable(
        url,
        json=payload,
        timeout=timeout,
        proxies=proxies,
    )


def _classify_response(
    status_code: int | None,
    received_bytes: int,
) -> str:
    """Return the closed outcome token for a returned response."""

    if status_code is None or status_code < 200 or status_code >= 300:
        return _OUTCOME_HTTP_STATUS
    if received_bytes <= 0:
        return _OUTCOME_EMPTY_RESPONSE
    return _OUTCOME_SUCCESS


def _run_attempt(
    *,
    post_callable: Callable[..., Any],
    mode: str,
    attempt: int,
    url: str,
    payload: dict[str, Any],
    timeout: tuple[float, float],
    proxies: dict[str, str],
) -> tuple[str, dict[str, Any]]:
    """Run a single attempt through ``post_callable`` and return a record."""

    started_utc = _utc_now_iso()
    started_mono = time.monotonic()
    try:
        response = _invoke_post(
            post_callable,
            url=url,
            payload=payload,
            timeout=timeout,
            proxies=proxies,
        )
    except requests.exceptions.RequestException as exc:
        outcome, safe_class = _classify_exception(exc)
        return _record_attempt(
            mode=mode,
            attempt=attempt,
            started_mono=started_mono,
            started_utc=started_utc,
            phase=_PHASE_EXCEPTION,
            outcome=outcome,
            http_status=None,
            received_bytes=None,
            exception_class=safe_class,
        )
    except Exception as exc:  # noqa: BLE001 - probe swallows unexpected failures safely
        outcome, safe_class = _classify_exception(exc)
        return _record_attempt(
            mode=mode,
            attempt=attempt,
            started_mono=started_mono,
            started_utc=started_utc,
            phase=_PHASE_EXCEPTION,
            outcome=outcome,
            http_status=None,
            received_bytes=None,
            exception_class=safe_class,
        )
    status_code, received_bytes = _consume_and_close(response)
    return _record_attempt(
        mode=mode,
        attempt=attempt,
        started_mono=started_mono,
        started_utc=started_utc,
        phase=_PHASE_RETURNED,
        outcome=_classify_response(status_code, received_bytes),
        http_status=status_code,
        received_bytes=received_bytes,
        exception_class=None,
    )


def run_probe(
    *,
    mode: str,
    count: int,
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
    settings_factory: Callable[[], Settings] | None = None,
    session_factory: Callable[[], requests.Session] | None = None,
    post_callable: Callable[..., Any] | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    """Run the diagnostic loop and return ``(exit_code, attempt_records)``.

    The function never re-raises; every failure is captured as a closed
    attempt record. Exit code is ``0`` only when every attempt reports
    ``outcome=success``; otherwise ``1``.
    """

    if mode not in _ALLOWED_MODES:
        raise ValueError(f"mode must be one of {_ALLOWED_MODES} (got {mode!r})")
    if not isinstance(count, int) or count <= 0:
        raise ValueError(f"count must be a positive integer (got {count!r})")
    if (
        not isinstance(connect_timeout_seconds, (int, float))
        or math.isnan(connect_timeout_seconds)
        or math.isinf(connect_timeout_seconds)
        or connect_timeout_seconds <= 0
    ):
        raise ValueError(
            "connect_timeout_seconds must be a positive finite number "
            f"(got {connect_timeout_seconds!r})"
        )
    if (
        not isinstance(read_timeout_seconds, (int, float))
        or math.isnan(read_timeout_seconds)
        or math.isinf(read_timeout_seconds)
        or read_timeout_seconds <= 0
    ):
        raise ValueError(
            "read_timeout_seconds must be a positive finite number "
            f"(got {read_timeout_seconds!r})"
        )

    factory = settings_factory or load_settings
    try:
        settings = factory()
    except Exception:  # noqa: BLE001 - probe swallows unexpected settings failures safely
        line, record = _record_configuration_error(mode=mode)
        print(line)
        return 1, [record]

    if not _validate_proxy_url(settings.ollama_proxy_url):
        line, record = _record_configuration_error(mode=mode)
        print(line)
        return 1, [record]

    proxies = _build_proxies(settings)
    payload = _build_payload(settings)
    timeout: tuple[float, float] = (
        float(connect_timeout_seconds),
        float(read_timeout_seconds),
    )

    records: list[dict[str, Any]] = []
    any_failure = False
    url = settings.llm_url

    if mode == _MODE_FRESH:
        post = post_callable or requests.post
        for attempt in range(1, count + 1):
            line, record = _run_attempt(
                post_callable=post,
                mode=mode,
                attempt=attempt,
                url=url,
                payload=payload,
                timeout=timeout,
                proxies=proxies,
            )
            print(line)
            records.append(record)
            if record["outcome"] != _OUTCOME_SUCCESS:
                any_failure = True
    else:
        session_ctor = session_factory or requests.Session
        session = session_ctor()
        try:
            for attempt in range(1, count + 1):
                line, record = _run_attempt(
                    post_callable=session.post,
                    mode=mode,
                    attempt=attempt,
                    url=url,
                    payload=payload,
                    timeout=timeout,
                    proxies=proxies,
                )
                print(line)
                records.append(record)
                if record["outcome"] != _OUTCOME_SUCCESS:
                    any_failure = True
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    return (1 if any_failure else 0), records


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    exit_code, _records = run_probe(
        mode=args.mode,
        count=args.count,
        connect_timeout_seconds=args.connect_timeout_seconds,
        read_timeout_seconds=args.read_timeout_seconds,
    )
    return exit_code


__all__ = [
    "_ALLOWED_MODES",
    "_ALLOWED_PROXY_SCHEMES",
    "_CONFIGURATION_ERROR_ATTEMPT",
    "_CONFIGURATION_ERROR_DURATION_MS",
    "_DEFAULT_CONNECT_TIMEOUT_SECONDS",
    "_DEFAULT_COUNT",
    "_DEFAULT_READ_TIMEOUT_SECONDS",
    "_MODE_FRESH",
    "_MODE_SESSION",
    "_OUTCOME_CONFIGURATION_ERROR",
    "_build_parser",
    "_build_payload",
    "_record_configuration_error",
    "_validate_proxy_url",
    "main",
    "run_probe",
]


if __name__ == "__main__":
    sys.exit(main())