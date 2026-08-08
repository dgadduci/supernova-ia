from __future__ import annotations

import argparse
import sys
import time

import requests

from backend.config.settings import load_settings
from backend.llm.embedding_client import EmbeddingClientError, OllamaEmbeddingClient
from backend.llm.query_llm import QueryLlm, QueryLlmError


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport-diagnostic", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    if args.transport_diagnostic:
        return run_transport_diagnostic(settings)

    started = time.monotonic()
    try:
        QueryLlm(settings=settings).request("Respond with exactly {}.")
    except QueryLlmError as exc:
        print(
            f"generate=failed category={type(exc).__name__} "
            f"model={settings.llm_model} elapsed_seconds={time.monotonic() - started:.4f}",
            file=sys.stderr,
        )
        return 1
    print(
        f"generate=passed model={settings.llm_model} "
        f"elapsed_seconds={time.monotonic() - started:.4f}"
    )

    started = time.monotonic()
    try:
        vector = OllamaEmbeddingClient(settings=settings).embed_query("health check")
    except EmbeddingClientError as exc:
        print(
            f"embed=failed category={type(exc).__name__} "
            f"model={settings.embedding_model} "
            f"elapsed_seconds={time.monotonic() - started:.4f}",
            file=sys.stderr,
        )
        return 1
    print(
        f"embed=passed model={settings.embedding_model} dimension={len(vector)} "
        f"elapsed_seconds={time.monotonic() - started:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
