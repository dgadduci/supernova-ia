"""Focused unit tests for ``normalize_for_embedding``.

The function MUST mirror the recognizer's ``_normalizar_texto`` exactly
so the same canonical text maps to the same normalized form across the
recognizer, the embedding document builder, and any future consumer.
A representative corpus asserts byte-identical output on lowercase,
accented, whitespace, digits, ``ñ``, and punctuation inputs.
"""
from __future__ import annotations

import unittest

from backend.embeddings.text_normalization import normalize_for_embedding
from backend.recognizers.product_recognizer import _normalizar_texto


class NormalizeForEmbeddingTest(unittest.TestCase):
    def test_lowercase(self):
        self.assertEqual(normalize_for_embedding("HELLO World"), "hello world")

    def test_accented_text_strips_diacritics(self):
        self.assertEqual(
            normalize_for_embedding("Muzzá"),
            "muzza",
        )

    def test_whitespace_collapse(self):
        self.assertEqual(
            normalize_for_embedding("Pizza  de   Muzzá   "),
            "pizza de muzza",
        )

    def test_digits_preserved(self):
        self.assertEqual(normalize_for_embedding("Coca 1L"), "coca 1l")

    def test_n_tilde_preserved(self):
        self.assertEqual(
            normalize_for_embedding("Mañana"),
            "manana",
        )

    def test_punctuation_becomes_space(self):
        self.assertEqual(
            normalize_for_embedding("Pizza, con! salsa?"),
            "pizza con salsa",
        )

    def test_non_string_input_raises(self):
        with self.assertRaises(ValueError):
            normalize_for_embedding(123)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            normalize_for_embedding(None)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            normalize_for_embedding(["hola"])  # type: ignore[arg-type]

    def test_byte_identical_to_recognizer_normalizer(self):
        corpus = [
            "Pizza de Muzzarella",
            "Pizza  de   Muzzá   ",
            "Coca Cola 1L",
            "Muzzá",
            "muzza",
            "Muzzárella",
            "Mañana",
            "Empanada de Carne",
            "Pizza, con! salsa?",
            "  ",
            "",
            "Pizza de Muzzarella Chica",
            "Pizza de Muzzarella Grande",
            "1 Litro",
            "Unidad",
        ]
        for sample in corpus:
            with self.subTest(sample=sample):
                self.assertEqual(
                    normalize_for_embedding(sample),
                    _normalizar_texto(sample),
                )


if __name__ == "__main__":
    unittest.main()
