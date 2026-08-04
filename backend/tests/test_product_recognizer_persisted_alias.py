"""Recognizer tests for the persisted-alias projection path.

Verifies that the fuzzy recognizer consumes caller-provided alias data
and preserves the frozen four-key result contract plus the original
unique, ambiguous, refinement, and known-limitation behavior.
"""
from __future__ import annotations

import unittest

from backend.recognizers.fuzzy_product_recognizer import FuzzyProductRecognizer
from backend.recognizers.product_recognizer import (
    ALIASES_PALABRAS,
    PRESENTACION_ALIASES,
    detectar_productos,
)


def _row(
    pp_id: int,
    nombre: str,
    *,
    codigo: str = "unidad",
    descripcion: str = "Unidad",
    aliases: dict | None = None,
) -> dict:
    row: dict = {
        "producto_presentacion_id": pp_id,
        "producto_id": pp_id,
        "presentacion_id": pp_id,
        "categoria_id": 1,
        "producto_nombre": nombre,
        "categoria_nombre": "Pizzas",
        "presentacion_codigo": codigo,
        "presentacion_descripcion": descripcion,
        "activo": True,
        "disponible": True,
    }
    if aliases is not None:
        row["aliases"] = aliases
    return row


def _ids(result) -> list[int]:
    found = [entry["producto_presentacion_id"] for entry in result["encontrados"]]
    possible = [
        entry["producto_presentacion_id"]
        for group in result["encontrados_posibles"]
        for entry in group["productos"]
    ]
    return found + possible


class PersistedAliasMatchTest(unittest.TestCase):
    def test_unique_match_via_general_persisted_alias(self):
        catalog = [
            _row(
                1,
                "Pizza Mozzarella",
                aliases={
                    "general_aliases": ["mozzarella"],
                    "specific_aliases": [],
                },
            )
        ]
        result = detectar_productos("pizza muzza", catalog)
        self.assertEqual(_ids(result), [1])
        self.assertEqual(result["encontrados"][0]["cantidad"], 1)

    def test_unique_match_via_specific_persisted_alias(self):
        catalog = [
            _row(
                1,
                "Pizza Mozzarella",
                codigo="chica",
                aliases={
                    "general_aliases": [],
                    "specific_aliases": ["mozzarella-chica"],
                },
            ),
            _row(
                2,
                "Pizza Mozzarella",
                codigo="grande",
                aliases={
                    "general_aliases": [],
                    "specific_aliases": ["mozzarella-grande"],
                },
            ),
        ]
        result = detectar_productos("pizza mozzarella-chica", catalog)
        self.assertEqual(_ids(result), [1])

    def test_general_alias_preserves_ambiguity_across_presentations(self):
        catalog = [
            _row(
                1,
                "Pizza Mozzarella",
                codigo="chica",
                aliases={
                    "general_aliases": ["mozzarella"],
                    "specific_aliases": [],
                },
            ),
            _row(
                2,
                "Pizza Mozzarella",
                codigo="grande",
                aliases={
                    "general_aliases": ["mozzarella"],
                    "specific_aliases": [],
                },
            ),
        ]
        result = detectar_productos("quiero una pizza muzza", catalog)
        self.assertEqual(result["encontrados"], [])
        possible_ids = _ids(result)
        self.assertEqual(sorted(possible_ids), [1, 2])

    def test_alias_absent_from_catalog_does_not_match(self):
        catalog = [_row(1, "Pizza Especial")]
        result = detectar_productos("pizza muzza", catalog)
        self.assertEqual(result["encontrados"], [])
        self.assertEqual(result["encontrados_posibles"], [])
        self.assertEqual(
            [entry["texto_origen"] for entry in result["no_encontrados"]],
            ["pizza muzza"],
        )

    def test_shared_alias_across_distinct_products_preserves_ambiguity(self):
        catalog = [
            _row(
                1,
                "Pizza Napolitana",
                aliases={
                    "general_aliases": ["napolitana"],
                    "specific_aliases": [],
                },
            ),
            _row(
                2,
                "Empanada Napolitana",
                aliases={
                    "general_aliases": ["napolitana"],
                    "specific_aliases": [],
                },
            ),
        ]
        result = detectar_productos("napoli mediana", catalog)
        possible_ids = _ids(result)
        self.assertIn(1, possible_ids)
        self.assertIn(2, possible_ids)

    def test_specific_alias_does_not_leak_to_sibling_presentation(self):
        catalog = [
            _row(
                1,
                "Pizza Mozzarella",
                codigo="chica",
                aliases={
                    "general_aliases": [],
                    "specific_aliases": ["muzza-chica"],
                },
            ),
            _row(
                2,
                "Pizza Mozzarella",
                codigo="grande",
                aliases={
                    "general_aliases": [],
                    "specific_aliases": [],
                },
            ),
        ]
        result = detectar_productos("pizza muzza-chica", catalog)
        ids = _ids(result)
        self.assertIn(1, ids)
        self.assertNotIn(2, ids)

    def test_recognizer_preserves_aliased_caller_fields(self):
        catalog = [
            _row(
                1,
                "Pizza Mozzarella",
                aliases={
                    "general_aliases": ["mozzarella"],
                    "specific_aliases": [],
                },
            )
        ]
        catalog[0]["caller_marker"] = "preserved"
        result = detectar_productos("pizza muzza", catalog)
        assert result["encontrados"]
        self.assertEqual(
            result["encontrados"][0].get("caller_marker"),
            "preserved",
        )

    def test_quantity_word_with_persisted_alias(self):
        catalog = [
            _row(
                1,
                "Pizza Mozzarella",
                aliases={
                    "general_aliases": ["mozzarella"],
                    "specific_aliases": [],
                },
            )
        ]
        result = detectar_productos("dos pizza muzza", catalog)
        self.assertEqual(_ids(result), [1])
        self.assertEqual(result["encontrados"][0]["cantidad"], 2)

    def test_recognizer_uses_protocol_via_fuzzy_adapter(self):
        catalog = [
            _row(
                1,
                "Pizza Mozzarella",
                aliases={
                    "general_aliases": ["mozzarella"],
                    "specific_aliases": [],
                },
            )
        ]
        recognizer = FuzzyProductRecognizer()
        result = recognizer.recognize("pizza muzza", catalog)
        self.assertEqual(_ids(result), [1])

    def test_structured_presentation_resolution_unchanged(self):
        catalog = [
            _row(1, "Pizza Mozzarella", codigo="chica", descripcion="Chica"),
            _row(2, "Pizza Mozzarella", codigo="grande", descripcion="Grande"),
        ]
        for token, expected_id in (("chica", 1), ("grande", 2)):
            with self.subTest(token=token):
                result = detectar_productos(
                    f"pizza muzza {token}", catalog
                )
                self.assertEqual(_ids(result), [expected_id])


class PersistedAliasContractTest(unittest.TestCase):
    def test_result_keys_match_frozen_contract(self):
        catalog = [_row(1, "Pizza Mozzarella")]
        result = detectar_productos("pizza muzzarella", catalog)
        self.assertEqual(
            list(result),
            [
                "encontrados",
                "encontrados_posibles",
                "encontrados_no_disponibles",
                "no_encontrados",
            ],
        )

    def test_recognizer_does_not_import_database_modules(self):
        import inspect

        from backend.recognizers import product_recognizer

        source = inspect.getsource(product_recognizer)
        for forbidden in (
            "from backend.models",
            "from backend.repositories",
            "from backend.services",
            "from sqlalchemy",
        ):
            self.assertNotIn(forbidden, source)

    def test_hardcoded_alias_map_preserved_for_seeder_reference(self):
        self.assertIn("muzza", ALIASES_PALABRAS)
        self.assertEqual(ALIASES_PALABRAS["muzza"], "mozzarella")

    def test_presentation_aliases_unchanged(self):
        self.assertEqual(
            PRESENTACION_ALIASES["chica"],
            "chica",
        )
        self.assertEqual(
            PRESENTACION_ALIASES["unidad"],
            "unidad",
        )


if __name__ == "__main__":
    unittest.main()
