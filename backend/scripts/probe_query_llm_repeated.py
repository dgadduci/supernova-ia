"""Standalone diagnostic CLI that repeatedly invokes :class:`QueryLlm`.

Run with::

    PYTHONPATH=. venv/bin/python -m backend.scripts.probe_query_llm_repeated

The probe reuses the existing :class:`QueryLlm.request` boundary together
with the service's configured settings. It deliberately does not
reimplement the HTTP transport, payload construction, proxy handling,
timeout logic or response parsing so the operator observation matches
exactly the same path the provider worker uses.

The probe is side-effect-free at the application layer:

* it does NOT open a database session;
* it does NOT send any provider message, create any order, perform any
  retry, lease or outbox row;
* it does NOT mutate the service settings, environment variables or the
  configured LLM URL/proxy.

The script is allowed to print the exact probe prompt and the parsed
LLM response because this is an operator-invoked diagnostic; it never
prints credentials, URLs, proxy values, headers, raw exception text or
tracebacks. Every attempt receives a fresh opaque correlation id so the
existing ``llm_request`` observability events can be aligned with the
operator-visible timestamps without leaking any sensitive content.
"""
from __future__ import annotations

import argparse
import math
import secrets
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from backend.config.settings import load_settings
from backend.llm.query_llm import QueryLlm, QueryLlmError

_DEFAULT_PROMPT = (
    "cambia mis empanadas de pollo por pizzas de mozzarella, "
    "agrega tres cocas en lata y saca las empanadas de carne"
)

_DEFAULT_COUNT = 10
_DEFAULT_DELAY_SECONDS = 0.0

_SLEEP: Callable[[float], None] = time.sleep


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string with ``Z``."""

    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _generate_correlation_id() -> str:
    """Return a fresh opaque correlation identifier.

    The value contains no prompt, response, customer, phone, credential,
    URL or proxy content; it is only an opaque hex token aligned with the
    safe correlation contract used by the ``llm_request`` events.
    """

    return f"probe-{secrets.token_hex(12)}"


def _format_response(response: Any) -> str:
    """Render the parsed :class:`QueryLlm` response for terminal output."""

    if isinstance(response, dict):
        return repr(response)
    return repr(response)


def _run_single_attempt(
    *,
    client: QueryLlm,
    prompt: str,
    attempt: int,
    total: int,
) -> tuple[bool, str]:
    """Run a single ``QueryLlm.request`` call and render the attempt block.

    Returns a tuple ``(success, line)`` where ``success`` indicates whether
    the call completed without raising and ``line`` is the closing line of
    the attempt block (either ``outcome=success ...`` or
    ``outcome=error ...``).
    """

    correlation_id = _generate_correlation_id()
    started_utc = _utc_now_iso()
    started_mono = time.monotonic()
    print(f"--- intento {attempt}/{total} ---")
    print(f"correlation_id={correlation_id}")
    print(f"inicio_utc={started_utc}")
    print(f"Mensaje enviado: {prompt}")
    try:
        response = client.request(prompt, correlation_id=correlation_id)
    except QueryLlmError as exc:
        finished_utc = _utc_now_iso()
        elapsed_ms = int((time.monotonic() - started_mono) * 1000)
        print(
            f"outcome=error exception_class={type(exc).__name__} "
            f"fin_utc={finished_utc} duracion_ms={elapsed_ms}"
        )
        return False, f"[intento {attempt}/{total}] outcome=error exception_class={type(exc).__name__}"
    except Exception as exc:  # noqa: BLE001 - probe swallows unexpected failures safely
        finished_utc = _utc_now_iso()
        elapsed_ms = int((time.monotonic() - started_mono) * 1000)
        safe_name = type(exc).__name__
        print(
            f"outcome=error exception_class={safe_name} "
            f"fin_utc={finished_utc} duracion_ms={elapsed_ms}"
        )
        return False, f"[intento {attempt}/{total}] outcome=error exception_class={safe_name}"
    finished_utc = _utc_now_iso()
    elapsed_ms = int((time.monotonic() - started_mono) * 1000)
    print(f"Respuesta recibida: {_format_response(response)}")
    print(
        f"outcome=success fin_utc={finished_utc} duracion_ms={elapsed_ms}"
    )
    return True, f"[intento {attempt}/{total}] outcome=success duracion_ms={elapsed_ms}"


def _resolve_count(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--count must be a positive integer (got {value!r})"
        ) from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(
            f"--count must be a positive integer (got {parsed})"
        )
    return parsed


def _resolve_delay(value: str) -> float:
    try:
        delay = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--delay-seconds must be a finite number (got {value!r})"
        ) from exc
    if math.isnan(delay) or math.isinf(delay) or delay < 0:
        raise argparse.ArgumentTypeError(
            f"--delay-seconds must be a finite non-negative number (got {value!r})"
        )
    return delay


def _resolve_prompt(value: str) -> str:
    if not value or not value.strip():
        raise argparse.ArgumentTypeError(
            "--prompt must be a non-empty string"
        )
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="probe_query_llm_repeated",
        description=(
            "Standalone diagnostic CLI that invokes the existing QueryLlm "
            "boundary repeatedly using the service's configured settings. "
            "The probe prints the exact message sent, the parsed response "
            "and bounded timing information for every attempt without "
            "persisting output or exposing credentials, URLs or proxy "
            "configuration."
        ),
    )
    parser.add_argument(
        "--count",
        type=_resolve_count,
        default=_DEFAULT_COUNT,
        help=(
            "Number of sequential QueryLlm attempts (positive integer, "
            f"default {_DEFAULT_COUNT})."
        ),
    )
    parser.add_argument(
        "--delay-seconds",
        type=_resolve_delay,
        default=_DEFAULT_DELAY_SECONDS,
        help=(
            "Delay applied ONLY between consecutive attempts, in seconds "
            "(non-negative finite number, default 0)."
        ),
    )
    parser.add_argument(
        "--prompt",
        type=_resolve_prompt,
        default=_DEFAULT_PROMPT,
        help=(
            "Non-empty prompt sent on every attempt. The default is a "
            "deterministic diagnostic text."
        ),
    )
    return parser


def run_probe(
    *,
    count: int,
    delay_seconds: float,
    prompt: str,
    sleep: Callable[[float], None] | None = None,
    settings_factory: Callable[[], Any] | None = None,
    client_factory: Callable[..., QueryLlm] | None = None,
) -> tuple[int, list[str]]:
    """Run the diagnostic probe loop.

    Returns ``(exit_code, per_attempt_status_lines)``. The ``exit_code``
    is ``0`` when every attempt succeeded and ``1`` when any attempt
    failed. ``per_attempt_status_lines`` is a list of closing lines, one
    per attempt, suitable for asserting in tests without reimplementing
    the print logic.
    """

    actual_sleep = sleep if sleep is not None else _SLEEP
    resolved_settings = (
        settings_factory() if settings_factory is not None else load_settings()
    )
    factory = client_factory or QueryLlm
    client = factory(settings=resolved_settings)
    if not isinstance(client, QueryLlm):
        raise TypeError("client_factory must return a QueryLlm instance")

    statuses: list[str] = []
    any_failure = False
    for attempt in range(1, count + 1):
        success, line = _run_single_attempt(
            client=client,
            prompt=prompt,
            attempt=attempt,
            total=count,
        )
        statuses.append(line)
        if not success:
            any_failure = True
        if attempt < count and delay_seconds > 0:
            actual_sleep(delay_seconds)
    return (1 if any_failure else 0), statuses


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    exit_code, _statuses = run_probe(
        count=args.count,
        delay_seconds=args.delay_seconds,
        prompt=args.prompt,
    )
    return exit_code


__all__ = [
    "_DEFAULT_COUNT",
    "_DEFAULT_DELAY_SECONDS",
    "_DEFAULT_PROMPT",
    "_build_parser",
    "main",
    "run_probe",
]


if __name__ == "__main__":
    sys.exit(main())
