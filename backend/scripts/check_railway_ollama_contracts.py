from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

import requests

from backend.config.settings import Settings, load_settings
from backend.llm.embedding_client import EmbeddingClientError, OllamaEmbeddingClient
from backend.llm.query_llm import QueryLlm, QueryLlmError

# Fixed controlled inputs for the readiness seam. They are intentionally
# unrelated to operator payloads or business content and are NEVER surfaced
# in :class:`OllamaReadinessResult` so the seam cannot leak the probe
# prompt or the probe text.
_OLLAMA_READINESS_PROBE_GENERATE_PROMPT = "Respond with exactly {}."
_OLLAMA_READINESS_PROBE_EMBED_INPUT = "health check"


@dataclass(frozen=True)
class OllamaReadinessResult:
    """Sanitized outcome of the controlled Ollama readiness probe.

    The seam is pure: it never opens a database session, never sends a
    provider message, never mutates business state, never caches rows
    or leases. A failure on either probe yields ``ready=False`` with a
    safe ``generate_category`` / ``embed_category`` equal to the
    exception class name (or ``generate_unexpected_error`` /
    ``embed_unexpected_error`` for unknown exceptions).

    The dataclass NEVER carries the probe inputs, the LLM response, the
    embedding vector, the configured URL/proxy or any other payload. The
    dimensions and durations are safe to log because they are bounded,
    derived values without customer/provider content.
    """

    ready: bool
    generate_category: str
    embed_category: str
    embed_dimension: int | None
    generate_duration_seconds: float
    embed_duration_seconds: float


def check_ollama_readiness(*, settings: Settings) -> OllamaReadinessResult:
    """Run the controlled generate + embedding readiness probe.

    The seam is side-effect-free: it opens no database session, sends no
    provider message, mutates no business state. Both probes use fixed
    controlled inputs that are NEVER surfaced in the return value, so the
    probe is reproducible and cannot leak operator or business content.

    The function never re-raises. Known or unexpected exceptions are
    reported as ``ready=False`` with a safe category equal to the
    exception class name. ``str(exc)`` and tracebacks are NEVER included
    in the returned dataclass.

    The embedding probe is skipped when the generate probe fails,
    matching the existing diagnostic CLI's short-circuit behavior. The
    skipped outcome is reported as
    ``embed_category="skipped_due_to_generate_failure"``.
    """
    started_generate = time.monotonic()
    generate_category = "passed"
    try:
        QueryLlm(settings=settings).request(
            _OLLAMA_READINESS_PROBE_GENERATE_PROMPT
        )
    except QueryLlmError as exc:
        generate_category = type(exc).__name__
    except Exception:  # noqa: BLE001 - probe must swallow every failure
        generate_category = "generate_unexpected_error"
    generate_elapsed = time.monotonic() - started_generate

    if generate_category != "passed":
        return OllamaReadinessResult(
            ready=False,
            generate_category=generate_category,
            embed_category="skipped_due_to_generate_failure",
            embed_dimension=None,
            generate_duration_seconds=generate_elapsed,
            embed_duration_seconds=0.0,
        )

    started_embed = time.monotonic()
    embed_category = "passed"
    embed_dimension: int | None = None
    try:
        vector = OllamaEmbeddingClient(settings=settings).embed_query(
            _OLLAMA_READINESS_PROBE_EMBED_INPUT
        )
    except EmbeddingClientError as exc:
        embed_category = type(exc).__name__
    except Exception:  # noqa: BLE001 - probe must swallow every failure
        embed_category = "embed_unexpected_error"
    else:
        embed_dimension = len(vector)
    embed_elapsed = time.monotonic() - started_embed

    return OllamaReadinessResult(
        ready=embed_category == "passed",
        generate_category=generate_category,
        embed_category=embed_category,
        embed_dimension=embed_dimension,
        generate_duration_seconds=generate_elapsed,
        embed_duration_seconds=embed_elapsed,
    )


def run_transport_diagnostic(settings) -> int:
    if settings.ollama_proxy_url != "socks5h://127.0.0.1:1055":
        print(
            "transport=embed connection=not_attempted http_status=none "
            "elapsed_seconds=0.0000 received_bytes=0 "
            "category=invalid_proxy_configuration"
        )
        return 1

    started = time.monotonic()
    status_code = None
    received_bytes = 0
    connection = "failed"
    category = "unknown"
    try:
        response = requests.post(
            settings.embedding_url,
            json={"model": settings.embedding_model, "input": ["health check"]},
            timeout=settings.embedding_timeout_seconds,
            proxies={
                "http": settings.ollama_proxy_url,
                "https": settings.ollama_proxy_url,
            },
            stream=True,
        )
        connection = "connected"
        status_code = response.status_code
        try:
            for chunk in response.iter_content(chunk_size=8192):
                received_bytes += len(chunk)
        finally:
            response.close()
        if status_code < 200 or status_code >= 300:
            category = "http_status"
        elif received_bytes == 0:
            category = "empty_response"
        else:
            category = "response_bytes_received"
    except requests.exceptions.Timeout:
        category = "timeout"
    except requests.exceptions.ConnectionError:
        category = "connection_error"
    except requests.exceptions.RequestException:
        category = "request_error"
    except (TypeError, ValueError, OSError):
        category = "diagnostic_error"
    elapsed = time.monotonic() - started
    status = str(status_code) if status_code is not None else "none"
    print(
        f"transport=embed connection={connection} status={category} "
        f"http_status={status} elapsed_seconds={elapsed:.4f} "
        f"received_bytes={received_bytes} category={category}"
    )
    return 0 if category == "response_bytes_received" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport-diagnostic", action="store_true")
    args = parser.parse_args(argv)
    settings = load_settings()
    if args.transport_diagnostic:
        return run_transport_diagnostic(settings)

    result = check_ollama_readiness(settings=settings)

    if result.generate_category != "passed":
        print(
            f"generate=failed category={result.generate_category} "
            f"model={settings.llm_model} "
            f"elapsed_seconds={result.generate_duration_seconds:.4f}",
            file=sys.stderr,
        )
        return 1
    print(
        f"generate=passed model={settings.llm_model} "
        f"elapsed_seconds={result.generate_duration_seconds:.4f}"
    )

    if result.embed_category != "passed":
        print(
            f"embed=failed category={result.embed_category} "
            f"model={settings.embedding_model} "
            f"elapsed_seconds={result.embed_duration_seconds:.4f}",
            file=sys.stderr,
        )
        return 1
    print(
        f"embed=passed model={settings.embedding_model} "
        f"dimension={result.embed_dimension} "
        f"elapsed_seconds={result.embed_duration_seconds:.4f}"
    )
    return 0


__all__ = [
    "OllamaReadinessResult",
    "check_ollama_readiness",
    "main",
    "run_transport_diagnostic",
]


if __name__ == "__main__":
    sys.exit(main())
