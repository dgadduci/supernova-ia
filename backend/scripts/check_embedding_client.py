"""Manual verification entry point for the local Ollama embedding client.

Run with::

    PYTHONPATH=. venv/bin/python -m backend.scripts.check_embedding_client

The script generates one real embedding using the configured Ollama
settings, prints the model, returned dimension, and elapsed time, and
hides the complete vector unless ``--print-vector`` is supplied. The
embed query text defaults to ``"hello world"`` and can be overridden with
``--text``. The exit code is non-zero when the embedding cannot be
generated or the returned dimension differs from the configured
expected dimension.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Sequence

from backend.config.settings import load_settings
from backend.llm.embedding_client import (
    EmbeddingClientError,
    OllamaEmbeddingClient,
)


_DEFAULT_TEXT = "hello world"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a real embedding using the configured local Ollama "
            "server and print model/dimension/elapsed time without exposing "
            "the full vector unless --print-vector is supplied."
        )
    )
    parser.add_argument(
        "--text",
        default=_DEFAULT_TEXT,
        help="Text to embed (default: %(default)r)",
    )
    parser.add_argument(
        "--print-vector",
        action="store_true",
        help="Print the complete embedding vector (default: hidden).",
    )
    return parser


def _format_vector_summary(vector: Sequence[float]) -> str:
    if not vector:
        return "<empty>"
    head = ", ".join(f"{value:.6f}" for value in vector[:3])
    return f"[len={len(vector)}, head=[{head}, ...]]"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    settings = load_settings()
    client = OllamaEmbeddingClient(settings=settings)
    text = args.text.strip() or _DEFAULT_TEXT
    started = time.monotonic()
    try:
        vector = client.embed_query(text)
    except EmbeddingClientError as exc:
        print(
            f"FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    elapsed = time.monotonic() - started
    expected = settings.embedding_dimension
    if len(vector) != expected:
        print(
            f"FAILED: dimension mismatch expected={expected} actual={len(vector)}",
            file=sys.stderr,
        )
        return 2
    print(f"model={settings.embedding_model}")
    print(f"url={settings.embedding_url}")
    print(f"dimension={len(vector)}")
    print(f"elapsed_seconds={elapsed:.4f}")
    if args.print_vector:
        print(f"vector={list(vector)}")
    else:
        print(f"vector={_format_vector_summary(vector)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())