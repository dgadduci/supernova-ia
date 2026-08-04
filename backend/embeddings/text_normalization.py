"""Deterministic text normalization for embedding documents.

The function in this module mirrors the lowercasing + Unicode NFD +
ASCII fallback + whitespace collapse algorithm used by the recognizer's
``_normalizar_texto`` so that the same canonical text maps to the same
normalized form across the recognizer, this embedding document builder,
and any future consumer. A focused test asserts byte-identical output
against the recognizer.

The module is intentionally infrastructure-free: it must not import
SQLAlchemy, repositories, HTTP, Ollama, pgvector, or product
recognizers.
"""
from __future__ import annotations

import re
import unicodedata


_DEFAULT_PATTERN = re.compile(r"[^a-z0-9ñ\s]")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_for_embedding(text: str) -> str:
    """Return the deterministic lowercased, accent-stripped, collapsed form.

    The algorithm follows the project's established normalization:

    1. ``text.lower()``
    2. ``unicodedata.normalize("NFD", text)``
    3. drop combining diacritics
    4. keep only ``[a-z0-9ñ\\s]``
    5. collapse internal whitespace
    6. strip leading/trailing whitespace

    The ``ñ`` character is preserved because the recognizer's policy
    treats it as a stable letter of the alphabet.
    """
    if not isinstance(text, str):
        raise ValueError(
            f"normalize_for_embedding requires a str input, got {type(text).__name__}"
        )
    lowered = text.lower()
    decomposed = unicodedata.normalize("NFD", lowered)
    stripped = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    cleaned = _DEFAULT_PATTERN.sub(" ", stripped)
    return _WHITESPACE_PATTERN.sub(" ", cleaned).strip()


__all__ = ["normalize_for_embedding"]
