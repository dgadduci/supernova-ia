"""Safely verify the configured Ollama generate and embedding contracts.

Run this only from the integrated Railway web-service container. It prints
safe metadata only: pass/fail, configured model, elapsed time, and embedding
dimension. It never prints prompts, model output, vectors, or credentials.
"""
from __future__ import annotations

import sys
import time

from backend.config.settings import load_settings
from backend.llm.embedding_client import EmbeddingClientError, OllamaEmbeddingClient
from backend.llm.query_llm import QueryLlm, QueryLlmError


def main() -> int:
    settings = load_settings()
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
